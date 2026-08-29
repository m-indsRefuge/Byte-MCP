$platformVariable = Get-Variable -Name IsWindows -ErrorAction SilentlyContinue
if ($null -eq $platformVariable) {
    $script:IsWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
}

Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
