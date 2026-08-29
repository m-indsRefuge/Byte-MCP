import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from types import MappingProxyType

from byte_mcp.errors import OXBundleError

from .repositories import GitRepository, SubsystemDefinition

PROTOCOL_VERSION = "ox-review-v1"
_CATEGORIES = ("source", "test", "boundary", "context")
_VERIFICATION_FIELDS = (
    "id",
    "kind",
    "command",
    "exit_code",
    "stdout",
    "stderr",
    "recorded_at",
    "provenance",
)
_VERIFICATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class BundleArtifact:
    logical_path: str
    categories: tuple[str, ...]
    byte_length: int
    sha256: str
    provider_text: str
    text_encoding: str


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    logical_path: str
    categories: tuple[str, ...]
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ReviewManifest:
    protocol_version: str
    repository_alias: str
    subsystem_id: str
    target_commit: str
    base_commit: str | None
    subsystem_definition_sha256: str
    entries: tuple[ManifestEntry, ...]
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedBundle:
    repository_alias: str
    subsystem_id: str
    target_commit: str
    base_commit: str | None
    subsystem_definition: Mapping[str, object]
    subsystem_definition_sha256: str
    repository_tree: tuple[str, ...]
    diff: BundleArtifact | None
    artifacts: tuple[BundleArtifact, ...]
    verification: tuple[Mapping[str, object], ...]
    manifest: ReviewManifest
    packet: Mapping[str, object]
    serialized_packet: bytes
    total_bytes: int


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value: object) -> bytes:
    try:
        encoded = json.dumps(
            _json_value(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise OXBundleError("bundle data must be canonical JSON") from error
    return encoded.encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, tuple | list):
        return tuple(_freeze(item) for item in value)
    return value


def _artifact(logical_path: str, categories: Sequence[str], raw: bytes) -> BundleArtifact:
    try:
        provider_text = raw.decode("utf-8")
        text_encoding = "utf-8"
    except UnicodeDecodeError:
        provider_text = raw.decode("utf-8", errors="replace")
        text_encoding = "utf-8-replacement"
    return BundleArtifact(
        logical_path,
        tuple(sorted(set(categories))),
        len(raw),
        hashlib.sha256(raw).hexdigest(),
        provider_text,
        text_encoding,
    )


def _artifact_payload(artifact: BundleArtifact) -> Mapping[str, object]:
    return MappingProxyType(
        {
            "logical_path": artifact.logical_path,
            "categories": artifact.categories,
            "byte_length": artifact.byte_length,
            "sha256": artifact.sha256,
            "provider_text": artifact.provider_text,
            "text_encoding": artifact.text_encoding,
        }
    )


def _definition_payload(definition: SubsystemDefinition) -> Mapping[str, object]:
    return MappingProxyType(
        {
            "subsystem_id": definition.subsystem_id,
            "version": definition.version,
            "source_roots": definition.source_roots,
            "test_roots": definition.test_roots,
            "boundary_files": definition.boundary_files,
            "context_files": definition.context_files,
        }
    )


def _json_manifest_entry(
    logical_path: str, categories: Sequence[str], value: object
) -> ManifestEntry:
    raw = _canonical_json(value)
    return ManifestEntry(
        logical_path,
        tuple(sorted(set(categories))),
        len(raw),
        hashlib.sha256(raw).hexdigest(),
    )


def _verification_payload(
    verification: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    if not verification:
        raise OXBundleError("verification evidence is mandatory")
    prepared: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    for record in verification:
        if not isinstance(record, Mapping) or any(
            field not in record for field in _VERIFICATION_FIELDS
        ):
            raise OXBundleError("verification evidence is incomplete")
        if not isinstance(record["stdout"], str) or not isinstance(record["stderr"], str):
            raise OXBundleError("verification stdout and stderr must be strings")
        if not isinstance(record["exit_code"], int) or isinstance(record["exit_code"], bool):
            raise OXBundleError("verification exit_code must be an integer")
        verification_id = record["id"]
        if (
            not isinstance(verification_id, str)
            or _VERIFICATION_ID.fullmatch(verification_id) is None
            or verification_id in seen_ids
        ):
            raise OXBundleError("verification ID must be a unique safe logical-path component")
        seen_ids.add(verification_id)
        payload = dict(record)
        payload["sha256"] = sha256_json(payload)
        prepared.append(MappingProxyType({key: _freeze(value) for key, value in payload.items()}))
    return tuple(prepared)


class BundleBuilder:
    def __init__(self, repository: GitRepository, *, max_bundle_bytes: int) -> None:
        if max_bundle_bytes < 0:
            raise ValueError("max_bundle_bytes must not be negative")
        self._repository = repository
        self._max_bundle_bytes = max_bundle_bytes

    def prepare(
        self,
        subsystem: SubsystemDefinition,
        target_commit: str,
        base_commit: str | None,
        verification: Sequence[Mapping[str, object]],
    ) -> PreparedBundle:
        try:
            target = self._repository.resolve_commit(target_commit)
            base = self._repository.resolve_commit(base_commit) if base_commit is not None else None
            categories_by_path: dict[str, set[str]] = {}
            category_roots = {
                "source": subsystem.source_roots,
                "test": subsystem.test_roots,
                "boundary": subsystem.boundary_files,
                "context": subsystem.context_files,
            }
            for category in _CATEGORIES:
                roots = category_roots[category]
                if not roots:
                    raise OXBundleError(f"mandatory {category} category has no configured paths")
                for root in roots:
                    paths = (
                        self._repository.iter_root_files(target, root)
                        if category in {"source", "test"}
                        else (root,)
                    )
                    for path in paths:
                        categories_by_path.setdefault(path, set()).add(category)
            artifacts = tuple(
                _artifact(path, categories_by_path[path], self._repository.read_file(target, path))
                for path in sorted(categories_by_path)
            )
            artifact_categories = {
                category for artifact in artifacts for category in artifact.categories
            }
            if artifact_categories != set(_CATEGORIES):
                raise OXBundleError("mandatory artifact category is missing")
            definition_payload = _definition_payload(subsystem)
            definition_sha256 = sha256_json(definition_payload)
            verification_payload = _verification_payload(verification)
            repository_tree = tuple(self._repository.repository_tree(target))
            diff = (
                _artifact(
                    "__ox__/base-to-target.diff", ("diff",), self._repository.diff(base, target)
                )
                if base is not None
                else None
            )
            entries = tuple(
                sorted(
                    [
                        *(
                            ManifestEntry(
                                artifact.logical_path,
                                artifact.categories,
                                artifact.byte_length,
                                artifact.sha256,
                            )
                            for artifact in artifacts
                        ),
                        _json_manifest_entry(
                            "__ox__/subsystem-definition.json",
                            ("subsystem-definition",),
                            definition_payload,
                        ),
                        _json_manifest_entry(
                            "__ox__/repository-tree.json", ("repository-tree",), repository_tree
                        ),
                        *(
                            [_json_manifest_entry("__ox__/base-to-target.diff", ("diff",), diff)]
                            if diff is not None
                            else []
                        ),
                        *(
                            _json_manifest_entry(
                                f"__ox__/verification/{record['id']}.json",
                                ("verification",),
                                record,
                            )
                            for record in verification_payload
                        ),
                    ],
                    key=lambda entry: entry.logical_path,
                )
            )
            manifest_payload = {
                "protocol_version": PROTOCOL_VERSION,
                "repository_alias": self._repository.definition.alias,
                "subsystem_id": subsystem.subsystem_id,
                "target_commit": target_commit,
                "base_commit": base_commit,
                "subsystem_definition_sha256": definition_sha256,
                "entries": tuple(asdict(entry) for entry in entries),
            }
            manifest = ReviewManifest(
                PROTOCOL_VERSION,
                self._repository.definition.alias,
                subsystem.subsystem_id,
                target_commit,
                base_commit,
                definition_sha256,
                entries,
                sha256_json(manifest_payload),
            )
            packet = MappingProxyType(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "repository": self._repository.definition.alias,
                    "subsystem": subsystem.subsystem_id,
                    "target_commit": target_commit,
                    "base_commit": base_commit,
                    "subsystem_definition": definition_payload,
                    "subsystem_definition_sha256": definition_sha256,
                    "repository_tree": repository_tree,
                    "diff": _artifact_payload(diff) if diff is not None else None,
                    "artifacts": tuple(_artifact_payload(artifact) for artifact in artifacts),
                    "verification": verification_payload,
                    "manifest": MappingProxyType(
                        {**manifest_payload, "manifest_sha256": manifest.manifest_sha256}
                    ),
                }
            )
            serialized_packet = _canonical_json(packet)
        except OXBundleError:
            raise
        except ValueError as error:
            raise OXBundleError("unable to construct required bundle artifact") from error
        total_bytes = len(serialized_packet)
        if total_bytes > self._max_bundle_bytes:
            raise OXBundleError(
                f"bundle size {total_bytes} exceeds max_bundle_bytes {self._max_bundle_bytes}"
            )
        return PreparedBundle(
            self._repository.definition.alias,
            subsystem.subsystem_id,
            target_commit,
            base_commit,
            definition_payload,
            definition_sha256,
            repository_tree,
            diff,
            artifacts,
            verification_payload,
            manifest,
            packet,
            serialized_packet,
            total_bytes,
        )
