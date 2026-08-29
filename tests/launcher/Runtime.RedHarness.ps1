# RED-only harness for the consolidated launcher runtime suite.
# These inert global functions exist only so Pester can Mock future commands
# before their production implementations exist. Every unmocked invocation
# deliberately throws, preserving the RED state of the subsystem.

function global:Test-LauncherProcessIdentity { throw 'NOT_IMPLEMENTED: Test-LauncherProcessIdentity' }
function global:Get-LauncherStateClassification { throw 'NOT_IMPLEMENTED: Get-LauncherStateClassification' }
function global:Invoke-LauncherHttpProbe { throw 'NOT_IMPLEMENTED: Invoke-LauncherHttpProbe' }
function global:Test-ByteMcpEndpoint { throw 'NOT_IMPLEMENTED: Test-ByteMcpEndpoint' }
function global:Test-TunnelHealth { throw 'NOT_IMPLEMENTED: Test-TunnelHealth' }
function global:Test-TunnelReady { throw 'NOT_IMPLEMENTED: Test-TunnelReady' }
function global:Test-ManagedServerProcess { throw 'NOT_IMPLEMENTED: Test-ManagedServerProcess' }
function global:Test-ManagedTunnelProcess { throw 'NOT_IMPLEMENTED: Test-ManagedTunnelProcess' }
function global:Get-ByteMcpStatus { throw 'NOT_IMPLEMENTED: Get-ByteMcpStatus' }
function global:Rotate-LauncherLog { throw 'NOT_IMPLEMENTED: Rotate-LauncherLog' }
function global:Start-LauncherServerProcess { throw 'NOT_IMPLEMENTED: Start-LauncherServerProcess' }
function global:Start-LauncherTunnelProcess { throw 'NOT_IMPLEMENTED: Start-LauncherTunnelProcess' }
function global:Wait-ByteMcpEndpoint { throw 'NOT_IMPLEMENTED: Wait-ByteMcpEndpoint' }
function global:Wait-TunnelHealth { throw 'NOT_IMPLEMENTED: Wait-TunnelHealth' }
function global:Wait-TunnelReady { throw 'NOT_IMPLEMENTED: Wait-TunnelReady' }
function global:Stop-LauncherCreatedProcess { throw 'NOT_IMPLEMENTED: Stop-LauncherCreatedProcess' }
function global:Start-LauncherForegroundServer { throw 'NOT_IMPLEMENTED: Start-LauncherForegroundServer' }
function global:Start-LauncherForegroundTunnel { throw 'NOT_IMPLEMENTED: Start-LauncherForegroundTunnel' }
function global:Confirm-LauncherListenersStopped { throw 'NOT_IMPLEMENTED: Confirm-LauncherListenersStopped' }
function global:Start-ByteMcpBackgroundStack { throw 'NOT_IMPLEMENTED: Start-ByteMcpBackgroundStack' }
function global:Start-ByteMcpForegroundStack { throw 'NOT_IMPLEMENTED: Start-ByteMcpForegroundStack' }
function global:Stop-ByteMcpManagedStack { throw 'NOT_IMPLEMENTED: Stop-ByteMcpManagedStack' }
