#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Build a plug-and-play USB installer for THE RESEARCHER on an Alienware m15.

.DESCRIPTION
    This script:
      1. Lists removable drives and asks you to pick one
      2. Collects target hostname / username / password for the new Linux machine
      3. Downloads Ventoy and formats the USB
      4. Downloads Ubuntu 24.04 Server ISO (cached in %LOCALAPPDATA%\researcher-usb)
      5. Copies the ISO to the VTOY partition
      6. Writes cloud-init autoinstall files (user-data / meta-data) to the USB
      7. Copies bootstrap.sh to the USB so the first-boot service can run it
      8. Writes ventoy.json to wire up the kernel append args and file injection

    When you boot the target machine from this USB:
      - Ubuntu installs unattended
      - On first login a systemd service runs bootstrap.sh (installs Ollama,
        pulls the model, clones the repo, starts the researcher service, opens SSH)
      - You can then connect from VS Code via Remote-SSH

.NOTES
    Requirements on this Windows machine:
      - Git for Windows (for openssl.exe — used to hash the password)
      - PowerShell 5.1+, run as Administrator
      - Internet access (downloads ~2 GB: Ventoy + Ubuntu ISO)
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Colours ───────────────────────────────────────────────────────────────────
function Write-Step   { param($m) Write-Host "`n$(('─'*60))`n  $m`n$(('─'*60))" -ForegroundColor Cyan }
function Write-Ok     { param($m) Write-Host "  [OK]  $m" -ForegroundColor Green }
function Write-Warn   { param($m) Write-Host "  [!]   $m" -ForegroundColor Yellow }
function Write-Fail   { param($m) Write-Host "`n  [ERR] $m`n" -ForegroundColor Red; exit 1 }
function Write-Info   { param($m) Write-Host "        $m" -ForegroundColor Gray }

# ── Banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ████████╗██╗  ██╗███████╗    ██████╗ ███████╗███████╗███████╗ █████╗ ██████╗  ██████╗██╗  ██╗███████╗██████╗ " -ForegroundColor Cyan
Write-Host "  ╚══██╔══╝██║  ██║██╔════╝    ██╔══██╗██╔════╝██╔════╝██╔════╝██╔══██╗██╔══██╗██╔════╝██║  ██║██╔════╝██╔══██╗" -ForegroundColor Cyan
Write-Host "     ██║   ███████║█████╗      ██████╔╝█████╗  ███████╗█████╗  ███████║██████╔╝██║     ███████║█████╗  ██████╔╝" -ForegroundColor Cyan
Write-Host "     ██║   ██╔══██║██╔══╝      ██╔══██╗██╔══╝  ╚════██║██╔══╝  ██╔══██║██╔══██╗██║     ██╔══██║██╔══╝  ██╔══██╗" -ForegroundColor Cyan
Write-Host "     ██║   ██║  ██║███████╗    ██║  ██║███████╗███████║███████╗██║  ██║██║  ██║╚██████╗██║  ██║███████╗██║  ██║" -ForegroundColor Cyan
Write-Host "     ╚═╝   ╚═╝  ╚═╝╚══════╝    ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Plug-and-Play USB Builder  |  Alienware m15 / Ubuntu 24.04" -ForegroundColor White
Write-Host ""

# ── Paths ─────────────────────────────────────────────────────────────────────
$ScriptDir   = $PSScriptRoot
$RepoRoot    = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path   # researcher/../ = repo root
$ResearcherDir = Join-Path $RepoRoot "researcher"
$CacheDir    = Join-Path $env:LOCALAPPDATA "researcher-usb"
$VentoyDir   = Join-Path $CacheDir "ventoy"
$VentoyApi   = "https://api.github.com/repos/ventoy/Ventoy/releases/latest"
$UbuntuReleasesBase = "https://releases.ubuntu.com/noble"

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null

# Resolve the current Ubuntu 24.04 LTS server ISO URL dynamically
Write-Info "Resolving current Ubuntu 24.04 LTS ISO..."
try {
    $releasePage = Invoke-WebRequest -Uri "$UbuntuReleasesBase/" -UseBasicParsing
    $isoFilename = ($releasePage.Links | Where-Object { $_.href -match 'ubuntu-24\.04.*-live-server-amd64\.iso$' -and $_.href -notmatch '\.torrent|\.zsync' } | Select-Object -First 1).href
    if (-not $isoFilename) { throw "No ISO link found on releases page." }
    # href may be a bare filename or a full URL
    if ($isoFilename -notmatch '^https?://') { $isoFilename = "$UbuntuReleasesBase/$isoFilename" }
    $IsoUrl      = $isoFilename
    $isoBasename = ($isoFilename -split '/')[-1]
    $IsoPath     = Join-Path $CacheDir $isoBasename
    Write-Ok "Found: $isoBasename"
} catch {
    Write-Warn "Could not auto-detect ISO URL ($_). Falling back to known URL."
    $IsoUrl  = "https://releases.ubuntu.com/noble/ubuntu-24.04.2-live-server-amd64.iso"
    $IsoPath = Join-Path $CacheDir "ubuntu-24.04.2-live-server-amd64.iso"
    $isoBasename = "ubuntu-24.04.2-live-server-amd64.iso"
}

# ── Step 1: Pick a drive ──────────────────────────────────────────────────────
Write-Step "1 / 7  Select USB drive"

$removable = Get-Disk | Where-Object { $_.BusType -eq 'USB' }
if (-not $removable) { Write-Fail "No USB drives found. Plug in your USB stick and re-run." }

Write-Host ""
Write-Host "  Removable drives detected:" -ForegroundColor White
$removable | ForEach-Object {
    $sizeGB = [math]::Round($_.Size / 1GB, 1)
    Write-Host ("    Disk {0}  -  {1} GB  -  {2}" -f $_.Number, $sizeGB, $_.FriendlyName) -ForegroundColor Yellow
}
Write-Host ""

[int]$diskNum = Read-Host "  Enter Disk Number to use (e.g. 1)"
$chosenDisk = $removable | Where-Object { $_.Number -eq $diskNum }
if (-not $chosenDisk) { Write-Fail "Disk $diskNum not found or is not a USB drive." }

$sizeGB = [math]::Round($chosenDisk.Size / 1GB, 1)
Write-Warn "You selected: Disk $diskNum - $sizeGB GB - $($chosenDisk.FriendlyName)"
Write-Warn "ALL DATA ON THIS DRIVE WILL BE ERASED."
Write-Host ""
$confirm = Read-Host '  Type  YES  to continue (anything else cancels)'
if ($confirm -ne 'YES') { Write-Host "  Cancelled." -ForegroundColor Yellow; exit 0 }

# ── Step 2: Collect target machine info ───────────────────────────────────────
Write-Step "2 / 7  Target machine configuration"
Write-Info "This info will be baked into the Ubuntu autoinstall config."
Write-Host ""

$targetHostname = Read-Host "  Hostname for the Linux machine (e.g. researcher)"
if (-not $targetHostname) { $targetHostname = "researcher" }

$targetUsername = Read-Host "  Username (e.g. your name, no spaces)"
if (-not $targetUsername) { $targetUsername = "researcher" }

$targetPassword = Read-Host "  Password for $targetUsername" -AsSecureString
$targetPassword2 = Read-Host "  Confirm password" -AsSecureString

$p1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($targetPassword))
$p2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($targetPassword2))
if ($p1 -ne $p2) { Write-Fail "Passwords do not match." }

# Hash the password using Git's bundled OpenSSL (SHA-512 crypt)
Write-Info "Hashing password..."
$gitOpenSsl = "C:\Program Files\Git\usr\bin\openssl.exe"
if (-not (Test-Path $gitOpenSsl)) {
    Write-Fail "Git for Windows not found at expected path.`n  Install Git from https://git-scm.com/download/win and re-run."
}
$passwordHash = & $gitOpenSsl passwd -6 $p1 2>$null
if (-not $passwordHash -or $passwordHash -notmatch '^\$6\$') {
    Write-Fail "Password hashing failed. Ensure Git for Windows is installed."
}
Write-Ok "Password hashed (SHA-512)"
$p1 = $null; $p2 = $null  # clear plaintext

# ── Step 3: Download Ventoy ───────────────────────────────────────────────────
Write-Step "3 / 7  Download Ventoy"

$ventoyZip = Join-Path $CacheDir "ventoy.zip"
if (Test-Path (Join-Path $VentoyDir "Ventoy2Disk.exe")) {
    Write-Ok "Ventoy already cached - skipping download"
} else {
    Write-Info "Fetching latest Ventoy release info..."
    $release = Invoke-RestMethod -Uri $VentoyApi -UseBasicParsing
    $asset = $release.assets | Where-Object { $_.name -like "*windows*" } | Select-Object -First 1
    if (-not $asset) { Write-Fail "Could not find Ventoy Windows asset in GitHub release." }
    Write-Info "Downloading $($asset.name) (~10 MB)..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $ventoyZip -UseBasicParsing
    Write-Info "Extracting..."
    Expand-Archive -Path $ventoyZip -DestinationPath $CacheDir -Force
    # Ventoy extracts to a versioned subfolder — find Ventoy2Disk.exe
    $exe = Get-ChildItem -Path $CacheDir -Recurse -Filter "Ventoy2Disk.exe" | Select-Object -First 1
    if (-not $exe) { Write-Fail "Ventoy2Disk.exe not found after extraction." }
    New-Item -ItemType Directory -Force -Path $VentoyDir | Out-Null
    Get-ChildItem -Path $exe.DirectoryName | ForEach-Object { Copy-Item $_.FullName $VentoyDir -Recurse -Force }
    Remove-Item $ventoyZip -Force
    Write-Ok "Ventoy ready at $VentoyDir"
}

# ── Step 4: Download Ubuntu ISO ───────────────────────────────────────────────
Write-Step "4 / 7  Download Ubuntu 24.04 Server ISO"

# Clean up any old misnamed cached ISO
Get-ChildItem -Path $CacheDir -Filter "ubuntu-*.iso" | Where-Object { $_.FullName -ne $IsoPath } | ForEach-Object {
    Write-Info "Removing stale cached ISO: $($_.Name)"
    Remove-Item $_.FullName -Force
}

if (Test-Path $IsoPath) {
    $sizeMB = [math]::Round((Get-Item $IsoPath).Length / 1MB)
    Write-Ok "ISO already cached ($sizeMB MB) - skipping download"
} else {
    Write-Info "Downloading $isoBasename (~2.7 GB) via BITS..."
    Write-Info "This will take a while - progress is shown in the Windows taskbar."
    Import-Module BitsTransfer
    Start-BitsTransfer -Source $IsoUrl -Destination $IsoPath -DisplayName "Ubuntu 24.04 ISO"
    Write-Ok "ISO downloaded to $IsoPath"
}

# ── Step 5: Install Ventoy and copy ISO ───────────────────────────────────────
Write-Step "5 / 7  Format USB and install Ventoy"

$ventoyExe = Join-Path $VentoyDir "Ventoy2Disk.exe"
Write-Warn "Formatting Disk $diskNum with Ventoy now..."
$proc = Start-Process -FilePath $ventoyExe -ArgumentList "/I", "\\.\PhysicalDrive$diskNum" -Wait -PassThru -NoNewWindow
if ($proc.ExitCode -ne 0) { Write-Fail "Ventoy2Disk.exe exited with code $($proc.ExitCode)." }
Write-Ok "Ventoy installed on Disk $diskNum"

# Wait for Windows to mount the VTOY partition
Write-Info "Waiting for VTOY partition to mount..."
$vtoyDrive = $null
$attempts = 0
while (-not $vtoyDrive -and $attempts -lt 20) {
    Start-Sleep -Seconds 3
    $attempts++
    $vtoyDrive = Get-Volume | Where-Object { $_.FileSystemLabel -eq 'VTOY' } | Select-Object -First 1
}
if (-not $vtoyDrive) { Write-Fail "VTOY partition did not appear after 60 s. Try re-running or assign it a drive letter manually." }
$vtoyLetter = "$($vtoyDrive.DriveLetter):\"
Write-Ok "VTOY mounted at $vtoyLetter"

Write-Info "Copying Ubuntu ISO to USB (~2.7 GB - may take several minutes)..."
Copy-Item -Path $IsoPath -Destination $vtoyLetter -Force
Write-Ok "ISO copied"

# ── Step 6: Write autoinstall + bootstrap files ───────────────────────────────
Write-Step "6 / 7  Write autoinstall config and bootstrap script"

$autoinstallDir = Join-Path $vtoyLetter "autoinstall"
New-Item -ItemType Directory -Force -Path $autoinstallDir | Out-Null

# meta-data (required by cloud-init nocloud, can be empty)
$metaDataSrc = Join-Path $ScriptDir "autoinstall\meta-data"
if (Test-Path $metaDataSrc) {
    Copy-Item $metaDataSrc (Join-Path $autoinstallDir "meta-data") -Force
} else {
    Set-Content -Path (Join-Path $autoinstallDir "meta-data") -Value "" -Encoding utf8
}

# user-data — substitute template placeholders
$userDataTemplate = Join-Path $ScriptDir "autoinstall\user-data.template"
if (-not (Test-Path $userDataTemplate)) {
    Write-Fail "user-data.template not found at $userDataTemplate"
}
$userData = Get-Content $userDataTemplate -Raw -Encoding utf8
$userData = $userData.Replace('{{HOSTNAME}}', $targetHostname)
$userData = $userData.Replace('{{USERNAME}}', $targetUsername)
$userData = $userData.Replace('{{PASSWORD_HASH}}', $passwordHash)
Set-Content -Path (Join-Path $autoinstallDir "user-data") -Value $userData -Encoding utf8
Write-Ok "user-data written"

# bootstrap.sh
$bootstrapSrc = Join-Path $ScriptDir "bootstrap.sh"
if (-not (Test-Path $bootstrapSrc)) { Write-Fail "bootstrap.sh not found at $bootstrapSrc" }
Copy-Item $bootstrapSrc (Join-Path $autoinstallDir "bootstrap.sh") -Force
Write-Ok "bootstrap.sh copied"

# ventoy.json — append_args + injection
$ventoyConfigDir = Join-Path $vtoyLetter "ventoy"
New-Item -ItemType Directory -Force -Path $ventoyConfigDir | Out-Null

$ventoyJson = @"
{
    "control": [
        { "VTOY_DEFAULT_SEARCH_ROOT": "/" }
    ],
    "append_args": [
        {
            "image": "/$isoBasename",
            "args": "autoinstall ds=nocloud;seedfrom=/cdrom/autoinstall/"
        }
    ],
    "injection": [
        {
            "image": "/$isoBasename",
            "archive": "autoinstall",
            "dir": "/autoinstall"
        }
    ]
}
"@
Set-Content -Path (Join-Path $ventoyConfigDir "ventoy.json") -Value $ventoyJson -Encoding utf8
Write-Ok "ventoy.json written"

# ── Step 7: Summary ───────────────────────────────────────────────────────────
Write-Step "7 / 7  Done!"

Write-Host ""
Write-Host "  USB is ready. Here's what to do next:" -ForegroundColor White
Write-Host ""
Write-Host "  1. Plug the USB into the Alienware m15." -ForegroundColor Gray
Write-Host "  2. Power on and press F12 to open the boot menu." -ForegroundColor Gray
Write-Host "  3. Select the USB drive." -ForegroundColor Gray
Write-Host "  4. Ventoy will boot - select the Ubuntu ISO." -ForegroundColor Gray
Write-Host "  5. Ubuntu installs completely unattended (~10-15 min)." -ForegroundColor Gray
Write-Host "  6. Machine reboots into Ubuntu." -ForegroundColor Gray
Write-Host "  7. On first boot, bootstrap.sh runs automatically:" -ForegroundColor Gray
Write-Host "       - Installs NVIDIA drivers, Ollama, pulls the AI model" -ForegroundColor Gray
Write-Host "       - Clones THE RESEARCHER and starts it as a service" -ForegroundColor Gray
Write-Host "       - Opens SSH on port 22, app on port 8009" -ForegroundColor Gray
Write-Host ""
Write-Host "  Connect from VS Code (Windows):" -ForegroundColor White
Write-Host "    - Add this to C:\Users\$($env:USERNAME)\.ssh\config :" -ForegroundColor Gray
Write-Host ""
Write-Host "        Host $targetHostname-lan" -ForegroundColor Yellow
Write-Host "            HostName LINUX-IP    # shown on screen after boot" -ForegroundColor Yellow
Write-Host "            User $targetUsername" -ForegroundColor Yellow
Write-Host "            Port 22" -ForegroundColor Yellow
Write-Host ""
Write-Host "    - Install the 'Remote - SSH' extension in VS Code" -ForegroundColor Gray
Write-Host "    - Ctrl+Shift+P -> Remote-SSH: Connect to Host -> $targetHostname-lan" -ForegroundColor Gray
Write-Host "    - Open folder: ~/researcher" -ForegroundColor Gray
Write-Host ""
Write-Host "  Researcher UI:  http://LINUX-IP:8009/ui" -ForegroundColor Cyan
Write-Host ""
