# when-free in the Windows notification area: a coloured dot, the status as its tooltip, and the details on click.
#
#   powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File when-free-tray.ps1
#
# To start it at sign-in, put a shortcut to that command in shell:startup.
# Needs `whenfree` on the PATH (pipx install when-free, or uv tool install when-free).

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function New-Dot([System.Drawing.Color]$colour) {
    $bitmap = New-Object System.Drawing.Bitmap 16, 16
    $g = [System.Drawing.Graphics]::FromImage($bitmap)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.FillEllipse((New-Object System.Drawing.SolidBrush $colour), 2, 2, 12, 12)
    $g.Dispose()
    return [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
}

$icons = @{
    busy  = New-Dot ([System.Drawing.Color]::FromArgb(224, 108, 117))
    free  = New-Dot ([System.Drawing.Color]::FromArgb(152, 195, 121))
    off   = New-Dot ([System.Drawing.Color]::FromArgb(171, 178, 191))
    error = New-Dot ([System.Drawing.Color]::FromArgb(229, 192, 123))
}

$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Visible = $true
$menu = New-Object System.Windows.Forms.ContextMenuStrip
[void]$menu.Items.Add("Refresh", $null, { Update-Status })
[void]$menu.Items.Add("Quit", $null, { $tray.Visible = $false; [System.Windows.Forms.Application]::Exit() })
$tray.ContextMenuStrip = $menu
$script:details = ""

function Update-Status {
    try {
        $raw = & whenfree now --format json 2>$null
        $st = $raw | ConvertFrom-Json
        if ($st.error) { throw $st.error }
        $line = (& whenfree now --format text 2>$null | Select-Object -First 1)
        if (-not $st.free_now) { $kind = "busy" } elseif ($st.in_hours) { $kind = "free" } else { $kind = "off" }
        $today = ($st.today | ForEach-Object { "$($_[0])-$($_[1])" }) -join ", "
        if (-not $today) { $today = "no free slot left" }
        $script:details = "$line`nToday: $today"
    } catch {
        $kind = "error"
        $line = "when-free: could not read your calendars"
        $script:details = "$_"
    }
    $tray.Icon = $icons[$kind]
    $tray.Text = $line.Substring(0, [Math]::Min(63, $line.Length))      # Windows limits tooltips to 63 characters
}

$tray.add_MouseClick({
    if ($_.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        $tray.ShowBalloonTip(5000, "when-free", $script:details, [System.Windows.Forms.ToolTipIcon]::None)
    }
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 60000
$timer.add_Tick({ Update-Status })
$timer.Start()
Update-Status
[System.Windows.Forms.Application]::Run()
