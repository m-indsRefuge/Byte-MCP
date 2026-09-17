#Requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][ValidateRange(1024,65535)][int] $Port)

$ErrorActionPreference = 'Stop'
$listener = [Net.HttpListener]::new()
$listener.Prefixes.Add("http://127.0.0.1:$Port/")
$listener.Start()
try {
    while ($true) {
        $context = $listener.GetContext()
        $body = switch ($context.Request.Url.AbsolutePath) {
            '/healthz' { 'live' }
            '/readyz' { 'ready' }
            default { 'rehearsal' }
        }
        $bytes = [Text.Encoding]::UTF8.GetBytes($body)
        $context.Response.StatusCode = 200
        $context.Response.ContentLength64 = $bytes.Length
        $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
        $context.Response.Close()
    }
}
finally { $listener.Stop(); $listener.Close() }
