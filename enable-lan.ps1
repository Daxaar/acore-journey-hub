param(
    [Parameter(Mandatory=$true)][string]$LanAddress,
    [string]$Distribution = 'Ubuntu',
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this script in Windows PowerShell as Administrator.' }
if ($Port -lt 1024 -or $Port -gt 65535 -or $Port -in @(3306,3724,3725,8085,8086)) { throw 'Choose a dashboard port, excluding game/database ports.' }
$address = [Net.IPAddress]::Parse($LanAddress)
if ($address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or $LanAddress -eq '0.0.0.0') { throw 'Provide the Windows LAN IPv4 address.' }
if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $LanAddress -ErrorAction SilentlyContinue)) { throw 'The LAN address is not assigned to this Windows machine.' }
$addresses = (& wsl.exe -d $Distribution -- hostname -I)
if ($LASTEXITCODE -ne 0) { throw 'Could not determine the WSL address.' }
$wslAddress = ($addresses.Trim() -split '\s+')[0]
$parsedWsl = [Net.IPAddress]::Parse($wslAddress)
if ($parsedWsl.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'WSL did not return an IPv4 address.' }
& netsh interface portproxy add v4tov4 listenaddress=$LanAddress listenport=$Port connectaddress=$wslAddress connectport=$Port
if ($LASTEXITCODE -ne 0) { throw 'Could not configure dashboard forwarding.' }
$ruleName = "JourneyHub-LAN-$Port"
# Replace either generation of this Hub's rule for the same port.
foreach ($existingRule in @($ruleName, "CharacterHub-LAN-$Port")) {
    if (Get-NetFirewallRule -Name $existingRule -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -Name $existingRule }
}
New-NetFirewallRule -Name $ruleName -DisplayName "Journey Hub LAN ($Port)" -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $LanAddress -LocalPort $Port -RemoteAddress LocalSubnet -Profile Any | Out-Null
Write-Host "Dashboard LAN URL: http://${LanAddress}:$Port"
Write-Host "Forwarding to WSL ${wslAddress}:$Port; firewall permits LocalSubnet only."
Write-Host 'Rerun after the WSL IP changes. Existing game/database forwarding rules are unchanged.'
