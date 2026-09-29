<#
.SYNOPSIS
    Step 6 of the ditch pipeline in one command: refresh both ditch property sets
    from current geometry, regenerate both CSV ведомости, and build the Excel
    workbook.

.DESCRIPTION
    Drives four Dynamo scripts in the already-open Civil 3D session via COM
    (no manual "Run" clicks), waits for each to finish, then runs the system
    Python Excel builder:
      1. ditch_05_build_cross_volumes - recompute cross-ditch PS from geometry
      2. ditch_06_report_cross        - cross-ditch ведомость (CSV)
      3. ditch_05_build_long_volumes  - recompute longitudinal PS from geometry
      4. ditch_06_report_long         - longitudinal ведомость (CSV)
      5. ditch_volumes_to_excel.py  - both ведомости -> the arhyz_s2_data repo's data\reports\ditch_volumes.xlsx

.NOTES
    Requires Civil 3D open with the ditch drawing. Run from a terminal:
      powershell -File automation\tools\update_ditch_volumes.ps1
#>

$ErrorActionPreference = "Stop"
$SCRIPTS = "C:\Arhyz\automation\scripts\ditch"

$acad = [Runtime.InteropServices.Marshal]::GetActiveObject("AutoCAD.Application")
$doc = $acad.ActiveDocument

function Invoke-Dyn {
    param($Name, $DynFwd, $LogDir, $Pattern)
    $before = (Get-ChildItem $LogDir -Filter $Pattern -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime | Select-Object -Last 1).Name
    $doc.SendCommand("FILEDIA`n0`n_.RUNDYNAMOSCRIPT`n$DynFwd`nFILEDIA`n1`n")
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $f = Get-ChildItem $LogDir -Filter $Pattern -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime | Select-Object -Last 1
        if ($f -and $f.Name -ne $before -and (Select-String -Path $f.FullName -Pattern "=== DONE" -Quiet)) {
            $tail = (Get-Content $f.FullName | Select-String "refreshed|converted .* polyline|exported|nothing to report").Line
            Write-Host "[$Name] $($f.Name)"
            if ($tail) { $tail | ForEach-Object { Write-Host "    $_" } }
            return
        }
        Start-Sleep -Seconds 3
    }
    Write-Warning "[$Name] no completed log within timeout"
}

Write-Host "== Cross ditches =="
Invoke-Dyn "cross refresh" "C:/Arhyz/automation/scripts/ditch/ditch_05_build_cross_volumes/ditch_05_build_cross_volumes.dyn" "$SCRIPTS\ditch_05_build_cross_volumes\logs" "refresh_*.log"
Invoke-Dyn "cross report" "C:/Arhyz/automation/scripts/ditch/ditch_06_report_cross/ditch_06_report_cross.dyn" "$SCRIPTS\ditch_06_report_cross\logs" "report_*.log"

Write-Host "== Longitudinal ditches =="
Invoke-Dyn "long refresh" "C:/Arhyz/automation/scripts/ditch/ditch_05_build_long_volumes/ditch_05_build_long_volumes.dyn" "$SCRIPTS\ditch_05_build_long_volumes\logs" "refresh_*.log"
Invoke-Dyn "long report" "C:/Arhyz/automation/scripts/ditch/ditch_06_report_long/ditch_06_report_long.dyn" "$SCRIPTS\ditch_06_report_long\logs" "report_*.log"

Write-Host "== Excel =="
& python "C:\Arhyz\automation\tools\ditch_volumes_to_excel.py"
