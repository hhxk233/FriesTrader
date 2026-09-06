[CmdletBinding()]
param([switch]$Preview, [string]$At)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run_cycle.py"
$shellPath = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
$arguments = @("-X", "utf8", $runner, "--powershell", $shellPath)
if ($Preview) { $arguments += "--preview" }
if ($At) { $arguments += @("--at", $At) }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "FriesTrader scheduled cycle failed; see the scheduled_cycle output." }
