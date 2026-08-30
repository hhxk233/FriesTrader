[CmdletBinding()]
param(
    [string]$Model = "gpt-5.6-luna",

    [ValidateSet("none", "low", "medium", "high", "xhigh", "max")]
    [string]$ReasoningEffort = "medium",

    [string]$CommitteeReportPath,

    [string]$CommitteeDecisionPath,

    [ValidateSet("auto", "intraday", "end_of_day")]
    [string]$ReviewMode = "auto",

    [ValidateSet("auto", "off", "always")]
    [string]$OpusEscalation = "auto",

    [ValidatePattern('^claude-opus-[a-z0-9-]+$')]
    [string]$OpusModel = "claude-opus-4-8",

    [ValidateSet("low", "medium", "high", "xhigh", "max")]
    [string]$OpusEffort = "high",

    [ValidateRange(0.05, 10.0)]
    [double]$OpusMaxBudgetUsd = 1.0,

    [ValidateSet("on", "off")]
    [string]$FreeNewsDesk = "on",

    [ValidateRange(1, 8)]
    [int]$FreeNewsAgents = 8,

    [ValidateRange(1, 4)]
    [int]$FreeNewsConcurrency = 2,

    [ValidateSet("auto", "codex_only")]
    [string]$FreeNewsProviderMode = "auto",

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._/-]*$')]
    [string]$FreeNewsFallbackModel = "gpt-5.6-luna",

    [ValidateSet("none", "low", "medium")]
    [string]$FreeNewsFallbackReasoningEffort = "low",

    [ValidatePattern('^(?:[01]\d|2[0-3]):[0-5]\d$')]
    [string]$EndOfDayCutoffCentral = "15:00",

    [switch]$Preview
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$committeeActiveVariable = "FRIESTRADER_COMMITTEE_ACTIVE"
if ([Environment]::GetEnvironmentVariable($committeeActiveVariable, "Process") -eq "1") {
    throw "Refusing to start a nested FriesTrader committee. The current Codex process is already the committee chair."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$promptPath = Join-Path $repoRoot "prompts\committee_review.md"
$opusHelperPath = Join-Path $scriptRoot "consult_opus.ps1"
$freeNewsHelperPath = Join-Path $scriptRoot "run_free_news_desk.ps1"
$riskRulesPath = Join-Path $repoRoot "risk_rules.json"
$strategyLibraryPath = Join-Path $repoRoot "strategy_library.json"
$privateConfigPath = if (-not [string]::IsNullOrWhiteSpace($env:FRIESTRADER_PRIVATE_CONFIG)) {
    $env:FRIESTRADER_PRIVATE_CONFIG
}
else {
    Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex\state\friestrader\local.json"
}

if (-not (Test-Path -LiteralPath $promptPath -PathType Leaf)) {
    throw "Committee prompt file not found: $promptPath"
}
if (-not (Test-Path -LiteralPath $riskRulesPath -PathType Leaf)) {
    throw "risk_rules.json not found: $riskRulesPath"
}
if (-not (Test-Path -LiteralPath $strategyLibraryPath -PathType Leaf)) {
    throw "strategy_library.json not found: $strategyLibraryPath"
}
if ($OpusEscalation -ne "off" -and -not (Test-Path -LiteralPath $opusHelperPath -PathType Leaf)) {
    throw "Opus consultation helper not found: $opusHelperPath"
}
if ($FreeNewsDesk -eq "on" -and -not (Test-Path -LiteralPath $freeNewsHelperPath -PathType Leaf)) {
    throw "Free news desk helper not found: $freeNewsHelperPath"
}
if (-not (Test-Path -LiteralPath $privateConfigPath -PathType Leaf)) {
    throw "Private FriesTrader config not found: $privateConfigPath"
}

$codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
if ($null -eq $codexCommand) {
    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
}
if ($null -eq $codexCommand) {
    throw "Codex CLI was not found on PATH. Install it and run 'codex login' first."
}
$codexCommandPath = [System.IO.Path]::GetFullPath([string]$codexCommand.Source)
$powerShellCommandPath = [string][System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
if ([string]::IsNullOrWhiteSpace($powerShellCommandPath) -or
    -not (Test-Path -LiteralPath $powerShellCommandPath -PathType Leaf) -or
    [System.IO.Path]::GetFileName($powerShellCommandPath) -notin @("powershell.exe", "pwsh.exe")) {
    $powerShellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($null -eq $powerShellCommand) {
        $powerShellCommand = Get-Command powershell.exe -ErrorAction SilentlyContinue
    }
    if ($null -eq $powerShellCommand) {
        throw "The current PowerShell executable could not be resolved."
    }
    $powerShellCommandPath = [string]$powerShellCommand.Source
}
$powerShellCommandPath = [System.IO.Path]::GetFullPath($powerShellCommandPath)
$claudeCommand = if ($OpusEscalation -eq "off") {
    $null
}
else {
    $resolvedClaudeCommand = Get-Command claude.cmd -ErrorAction SilentlyContinue
    if ($null -eq $resolvedClaudeCommand) {
        $resolvedClaudeCommand = Get-Command claude -ErrorAction SilentlyContinue
    }
    $resolvedClaudeCommand
}
$opusAvailable = $null -ne $claudeCommand
$claudeCommandPath = if ($opusAvailable) {
    [System.IO.Path]::GetFullPath([string]$claudeCommand.Source)
}
else {
    ""
}
if ($opusAvailable) {
    $claudeShimDirectory = Split-Path -Parent $claudeCommandPath
    $nativeClaudeCandidate = Join-Path $claudeShimDirectory "node_modules\@anthropic-ai\claude-code\bin\claude.exe"
    if (Test-Path -LiteralPath $nativeClaudeCandidate -PathType Leaf) {
        $claudeCommandPath = [System.IO.Path]::GetFullPath($nativeClaudeCandidate)
    }
}
if ($OpusEscalation -eq "always" -and -not $opusAvailable) {
    throw "Opus escalation is set to always, but Claude CLI was not found on PATH."
}

$privateConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $privateConfigPath | ConvertFrom-Json
$runtimeAccountNumber = [string]$privateConfig.account_number
$runtimeLinkedAccounts = @($privateConfig.linked_accounts | ForEach-Object { [string]$_ })
if ([string]::IsNullOrWhiteSpace($runtimeAccountNumber) -or $runtimeLinkedAccounts.Count -eq 0) {
    throw "Private FriesTrader config is missing account_number or linked_accounts."
}

$centralTimeZone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
$centralNow = [System.TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $centralTimeZone)
$endOfDayCutoff = [TimeSpan]::ParseExact(
    $EndOfDayCutoffCentral,
    "hh\:mm",
    [System.Globalization.CultureInfo]::InvariantCulture
)
$resolvedReviewMode = if ($ReviewMode -eq "auto") {
    if ($centralNow.TimeOfDay -ge $endOfDayCutoff) { "end_of_day" } else { "intraday" }
}
else {
    $ReviewMode
}
$logsPath = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null
$runStamp = $centralNow.ToString("yyyyMMdd-HHmmss")
$reportPath = if ([string]::IsNullOrWhiteSpace($CommitteeReportPath)) {
    Join-Path $logsPath ("committee-review-{0}.md" -f $runStamp)
}
else {
    [System.IO.Path]::GetFullPath($CommitteeReportPath)
}
$decisionPath = if ([string]::IsNullOrWhiteSpace($CommitteeDecisionPath)) {
    Join-Path $logsPath ("committee-decision-{0}.json" -f $runStamp)
}
else {
    [System.IO.Path]::GetFullPath($CommitteeDecisionPath)
}
$opusRequestPath = Join-Path $logsPath ("opus-consult-request-{0}.md" -f $runStamp)
$opusResultPath = Join-Path $logsPath ("opus-consult-result-{0}.json" -f $runStamp)
$freeNewsPacketPath = Join-Path $logsPath ("free-news-packet-{0}.json" -f $runStamp)
$freeNewsResultPath = Join-Path $logsPath ("free-news-desk-{0}.json" -f $runStamp)
$logsPrefix = [System.IO.Path]::GetFullPath($logsPath).TrimEnd('\') + '\'
foreach ($outputPath in @($reportPath, $decisionPath, $opusRequestPath, $opusResultPath, $freeNewsPacketPath, $freeNewsResultPath)) {
    if (-not $outputPath.StartsWith($logsPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Committee output paths must stay under $logsPath"
    }
}
$runLogPath = Join-Path $logsPath ("codex-committee-{0}.log" -f $centralNow.ToString("yyyyMMdd-HHmmss"))

$codexArgs = @(
    "-C", $repoRoot,
    "-a", "never",
    "-s", "workspace-write",
    "-c", "sandbox_workspace_write.network_access=true",
    "-c", "mcp_servers.robinhood-trading.required=true",
    "-c", "model_reasoning_effort=$ReasoningEffort",
    "--search"
)
if (-not [string]::IsNullOrWhiteSpace($Model)) {
    $codexArgs += @("-m", $Model)
}
if ($opusAvailable) {
    $codexArgs += @("--add-dir", (Split-Path -Parent $claudeCommandPath))
}
$codexArgs += @("exec", "--ephemeral", "--color", "never", "-")

if ($Preview) {
    Write-Output ("Committee date: " + $centralNow.ToString("yyyy-MM-dd"))
    Write-Output ("Review mode: " + $resolvedReviewMode)
    Write-Output "End-of-day cutoff Central: $EndOfDayCutoffCentral"
    Write-Output ("Report path: " + $reportPath)
    Write-Output ("Decision path: " + $decisionPath)
    Write-Output "Codex working directory: $repoRoot"
    Write-Output "Chair model: $Model"
    Write-Output "Reasoning effort: $ReasoningEffort"
    Write-Output "Opus escalation: $OpusEscalation"
    Write-Output "Opus available: $($opusAvailable.ToString().ToLowerInvariant())"
    Write-Output "Opus command path: $claudeCommandPath"
    Write-Output "Opus model: $OpusModel"
    Write-Output "Opus effort: $OpusEffort"
    Write-Output "Opus max budget USD: $OpusMaxBudgetUsd"
    Write-Output "Free news desk: $FreeNewsDesk"
    Write-Output "Free news agents: $FreeNewsAgents"
    Write-Output "Free news concurrency: $FreeNewsConcurrency"
    Write-Output "Free news provider mode: $FreeNewsProviderMode"
    Write-Output "Free news fallback model: $FreeNewsFallbackModel"
    Write-Output "Free news fallback reasoning effort: $FreeNewsFallbackReasoningEffort"
    Write-Output "PowerShell command path: $powerShellCommandPath"
    exit 0
}

if (-not $env:CODEX_API_KEY) {
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $loginOutput = @(& $codexCommandPath login status 2>&1)
        $loginExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($loginExitCode -ne 0) {
        $loginDetails = (($loginOutput | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
        if ([string]::IsNullOrWhiteSpace($loginDetails)) {
            $loginDetails = "No diagnostic output was returned."
        }
        throw "Codex CLI authentication check failed with exit code $loginExitCode using '$codexCommandPath':`n$loginDetails"
    }
}

$savedErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $mcpOutput = @(& $codexCommandPath mcp get robinhood-trading --json 2>&1)
    $mcpExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $savedErrorActionPreference
}
if ($mcpExitCode -ne 0) {
    $mcpDetails = (($mcpOutput | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($mcpDetails)) {
        $mcpDetails = "No diagnostic output was returned."
    }
    throw "Required MCP server 'robinhood-trading' check failed with exit code $mcpExitCode using '$codexCommandPath':`n$mcpDetails"
}

$prompt = Get-Content -Raw -Encoding UTF8 -LiteralPath $promptPath
$prompt = $prompt.Replace("<central_date>", $centralNow.ToString("yyyy-MM-dd"))
$prompt = $prompt.Replace("<review_mode>", $resolvedReviewMode)
$prompt = $prompt.Replace("<committee_report_path>", $reportPath)
$prompt = $prompt.Replace("<committee_decision_path>", $decisionPath)
$prompt = $prompt.Replace("<opus_escalation_mode>", $OpusEscalation)
$prompt = $prompt.Replace("<opus_available>", $opusAvailable.ToString().ToLowerInvariant())
$prompt = $prompt.Replace("<opus_model>", $OpusModel)
$prompt = $prompt.Replace("<opus_effort>", $OpusEffort)
$prompt = $prompt.Replace("<opus_max_budget_usd>", $OpusMaxBudgetUsd.ToString([System.Globalization.CultureInfo]::InvariantCulture))
$prompt = $prompt.Replace("<opus_helper_path>", $opusHelperPath)
$prompt = $prompt.Replace("<opus_command_path>", $claudeCommandPath)
$prompt = $prompt.Replace("<opus_request_path>", $opusRequestPath)
$prompt = $prompt.Replace("<opus_result_path>", $opusResultPath)
$prompt = $prompt.Replace("<free_news_desk_mode>", $FreeNewsDesk)
$prompt = $prompt.Replace("<free_news_agents>", [string]$FreeNewsAgents)
$prompt = $prompt.Replace("<free_news_concurrency>", [string]$FreeNewsConcurrency)
$prompt = $prompt.Replace("<free_news_provider_mode>", $FreeNewsProviderMode)
$prompt = $prompt.Replace("<free_news_fallback_model>", $FreeNewsFallbackModel)
$prompt = $prompt.Replace("<free_news_fallback_reasoning_effort>", $FreeNewsFallbackReasoningEffort)
$prompt = $prompt.Replace("<codex_command_path>", $codexCommandPath)
$prompt = $prompt.Replace("<powershell_command_path>", $powerShellCommandPath)
$prompt = $prompt.Replace("<free_news_helper_path>", $freeNewsHelperPath)
$prompt = $prompt.Replace("<free_news_packet_path>", $freeNewsPacketPath)
$prompt = $prompt.Replace("<free_news_result_path>", $freeNewsResultPath)
$runtimeContext = [ordered]@{
    account_number = $runtimeAccountNumber
    linked_accounts = $runtimeLinkedAccounts
} | ConvertTo-Json -Depth 3 -Compress
$prompt += @"

PRIVATE RUNTIME CONTEXT
Use this only for read-only Robinhood account lookups. Do not print, log, commit, or persist full account numbers:
$runtimeContext
"@

$originalRiskRulesText = Get-Content -Raw -Encoding UTF8 -LiteralPath $riskRulesPath
$originalRiskRules = $originalRiskRulesText | ConvertFrom-Json
if ($null -eq $originalRiskRules.personalization) {
    throw "risk_rules.json is missing the required personalization object."
}
$originalStrategyLibraryText = Get-Content -Raw -Encoding UTF8 -LiteralPath $strategyLibraryPath
try {
    $originalStrategyLibrary = $originalStrategyLibraryText | ConvertFrom-Json
}
catch {
    throw "strategy_library.json is invalid JSON."
}
$originalStrategyLibraryJson = $originalStrategyLibrary | ConvertTo-Json -Depth 100 -Compress

function ConvertTo-ImmutableRiskJson {
    param([Parameter(Mandatory = $true)][string]$JsonText)

    $rules = $JsonText | ConvertFrom-Json
    $rules.PSObject.Properties.Remove("personalization")
    return ($rules | ConvertTo-Json -Depth 100 -Compress)
}

$originalImmutableRiskJson = ConvertTo-ImmutableRiskJson -JsonText $originalRiskRulesText
$originalPersonalizationJson = $originalRiskRules.personalization | ConvertTo-Json -Depth 20 -Compress

function Restore-CommitteeFilesAndThrow {
    param([Parameter(Mandatory = $true)][string]$Message)

    $currentRiskRulesText = if (Test-Path -LiteralPath $riskRulesPath -PathType Leaf) {
        Get-Content -Raw -Encoding UTF8 -LiteralPath $riskRulesPath
    }
    else {
        $null
    }
    if ($currentRiskRulesText -ne $originalRiskRulesText) {
        [System.IO.File]::WriteAllText($riskRulesPath, $originalRiskRulesText, (New-Object System.Text.UTF8Encoding($false)))
    }

    $currentStrategyLibraryText = if (Test-Path -LiteralPath $strategyLibraryPath -PathType Leaf) {
        Get-Content -Raw -Encoding UTF8 -LiteralPath $strategyLibraryPath
    }
    else {
        $null
    }
    if ($currentStrategyLibraryText -ne $originalStrategyLibraryText) {
        [System.IO.File]::WriteAllText($strategyLibraryPath, $originalStrategyLibraryText, (New-Object System.Text.UTF8Encoding($false)))
    }

    throw $Message
}

$sensitiveAccountNumbers = @($runtimeAccountNumber) + $runtimeLinkedAccounts | Sort-Object -Unique

Write-Host "Starting the FriesTrader investment committee with Codex CLI."
Write-Host "Review mode: $resolvedReviewMode"
Write-Host "Committee report: $reportPath"
Write-Host "Committee decision: $decisionPath"
Write-Host "Combined run log: $runLogPath"
Write-Host "Opus escalation: $OpusEscalation (available: $($opusAvailable.ToString().ToLowerInvariant()), model: $OpusModel)"
Write-Host "Free public-news desk: $FreeNewsDesk ($FreeNewsAgents agents, concurrency $FreeNewsConcurrency, provider $FreeNewsProviderMode, fallback $FreeNewsFallbackModel/$FreeNewsFallbackReasoningEffort)"

$previousGitConfigCount = [Environment]::GetEnvironmentVariable("GIT_CONFIG_COUNT", "Process")
$gitConfigIndex = if ([string]::IsNullOrWhiteSpace($previousGitConfigCount)) { 0 } else { [int]$previousGitConfigCount }
$gitConfigKeyName = "GIT_CONFIG_KEY_$gitConfigIndex"
$gitConfigValueName = "GIT_CONFIG_VALUE_$gitConfigIndex"
$previousGitConfigKey = [Environment]::GetEnvironmentVariable($gitConfigKeyName, "Process")
$previousGitConfigValue = [Environment]::GetEnvironmentVariable($gitConfigValueName, "Process")
$previousCommitteeActive = [Environment]::GetEnvironmentVariable($committeeActiveVariable, "Process")
[Environment]::SetEnvironmentVariable($gitConfigKeyName, "safe.directory", "Process")
[Environment]::SetEnvironmentVariable($gitConfigValueName, $repoRoot.Replace('\', '/'), "Process")
[Environment]::SetEnvironmentVariable("GIT_CONFIG_COUNT", [string]($gitConfigIndex + 1), "Process")
[Environment]::SetEnvironmentVariable($committeeActiveVariable, "1", "Process")

$savedErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $prompt | & $codexCommandPath @codexArgs 2>&1 | ForEach-Object {
        $sanitizedLine = [string]$_
        foreach ($accountValue in $sensitiveAccountNumbers) {
            $maskedValue = if ($accountValue.Length -gt 4) {
                "****" + $accountValue.Substring($accountValue.Length - 4)
            }
            else {
                "****"
            }
            $sanitizedLine = $sanitizedLine.Replace($accountValue, $maskedValue)
        }
        if ($sanitizedLine -ne "System.Management.Automation.RemoteException") {
            $sanitizedLine
        }
    } | Tee-Object -FilePath $runLogPath
    $codexExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $savedErrorActionPreference
    [Environment]::SetEnvironmentVariable($gitConfigKeyName, $previousGitConfigKey, "Process")
    [Environment]::SetEnvironmentVariable($gitConfigValueName, $previousGitConfigValue, "Process")
    [Environment]::SetEnvironmentVariable("GIT_CONFIG_COUNT", $previousGitConfigCount, "Process")
    [Environment]::SetEnvironmentVariable($committeeActiveVariable, $previousCommitteeActive, "Process")
}

if ($codexExitCode -ne 0) {
    Restore-CommitteeFilesAndThrow "Codex CLI exited with code $codexExitCode. See $runLogPath"
}

if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    Restore-CommitteeFilesAndThrow "Committee completed without writing its report: $reportPath"
}
if (-not (Test-Path -LiteralPath $decisionPath -PathType Leaf)) {
    Restore-CommitteeFilesAndThrow "Committee completed without writing its decision JSON: $decisionPath"
}

$updatedRiskRulesText = Get-Content -Raw -Encoding UTF8 -LiteralPath $riskRulesPath
try {
    $updatedRiskRules = $updatedRiskRulesText | ConvertFrom-Json
}
catch {
    Restore-CommitteeFilesAndThrow "Committee produced invalid risk_rules.json; the original committee-owned files were restored."
}

$updatedImmutableRiskJson = ConvertTo-ImmutableRiskJson -JsonText $updatedRiskRulesText
if ($updatedImmutableRiskJson -ne $originalImmutableRiskJson) {
    Restore-CommitteeFilesAndThrow "Committee changed risk_rules outside personalization; the original committee-owned files were restored."
}

$allowedPersonalizationKeys = @(
    "_comment",
    "revision",
    "last_reviewed_central",
    "research_focus",
    "preferred_setups",
    "avoid_patterns",
    "watchlist_notes",
    "scan_notes",
    "lessons_learned"
)
$actualPersonalizationKeys = @($updatedRiskRules.personalization.PSObject.Properties.Name)
$unexpectedKeys = @($actualPersonalizationKeys | Where-Object { $_ -notin $allowedPersonalizationKeys })
$missingKeys = @($allowedPersonalizationKeys | Where-Object { $_ -notin $actualPersonalizationKeys })
if ($unexpectedKeys.Count -gt 0 -or $missingKeys.Count -gt 0) {
    Restore-CommitteeFilesAndThrow "Committee changed the personalization schema; the original committee-owned files were restored."
}
if ([string]$updatedRiskRules.personalization._comment -ne [string]$originalRiskRules.personalization._comment) {
    Restore-CommitteeFilesAndThrow "Committee changed personalization._comment; the original committee-owned files were restored."
}

$updatedRevision = 0L
if (-not [long]::TryParse([string]$updatedRiskRules.personalization.revision, [ref]$updatedRevision) -or $updatedRevision -lt 0) {
    Restore-CommitteeFilesAndThrow "Committee wrote an invalid personalization revision; the original committee-owned files were restored."
}
if ($null -ne $updatedRiskRules.personalization.last_reviewed_central -and
    -not ($updatedRiskRules.personalization.last_reviewed_central -is [string])) {
    Restore-CommitteeFilesAndThrow "Committee wrote an invalid personalization review timestamp; the original committee-owned files were restored."
}

$personalizationListKeys = @(
    "research_focus",
    "preferred_setups",
    "avoid_patterns",
    "watchlist_notes",
    "scan_notes",
    "lessons_learned"
)
foreach ($key in $personalizationListKeys) {
    $items = @($updatedRiskRules.personalization.$key)
    if ($items.Count -gt 8 -or @($items | Where-Object { -not ($_ -is [string]) -or $_.Length -gt 300 }).Count -gt 0) {
        Restore-CommitteeFilesAndThrow "Committee wrote invalid personalization content in $key; the original committee-owned files were restored."
    }
}

function Test-ExactKeys {
    param(
        $Object,
        [Parameter(Mandatory = $true)][string[]]$Keys
    )

    if ($null -eq $Object) {
        return $false
    }
    $actualKeys = @($Object.PSObject.Properties.Name)
    return (@($actualKeys | Where-Object { $_ -notin $Keys }).Count -eq 0 -and
        @($Keys | Where-Object { $_ -notin $actualKeys }).Count -eq 0)
}

function Test-StringList {
    param(
        $Value,
        [Parameter(Mandatory = $true)][int]$MaxItems,
        [Parameter(Mandatory = $true)][int]$MaxLength
    )

    if ($null -eq $Value) {
        return $false
    }
    $items = @($Value)
    return ($items.Count -le $MaxItems -and
        @($items | Where-Object { -not ($_ -is [string]) -or $_.Length -gt $MaxLength }).Count -eq 0)
}

function Test-NonNegativeInteger {
    param($Value)

    $parsed = 0L
    return ([long]::TryParse([string]$Value, [ref]$parsed) -and $parsed -ge 0)
}

$updatedStrategyLibraryText = Get-Content -Raw -Encoding UTF8 -LiteralPath $strategyLibraryPath
if ($resolvedReviewMode -eq "intraday" -and $updatedStrategyLibraryText -ne $originalStrategyLibraryText) {
    Restore-CommitteeFilesAndThrow "An intraday committee changed strategy_library.json; the original committee-owned files were restored."
}
try {
    $updatedStrategyLibrary = $updatedStrategyLibraryText | ConvertFrom-Json
}
catch {
    Restore-CommitteeFilesAndThrow "Committee produced invalid strategy_library.json; the original committee-owned files were restored."
}

$strategyLibraryKeys = @(
    "_comment",
    "version",
    "revision",
    "last_updated_central",
    "strategies",
    "evidence_ledger",
    "change_log"
)
if (-not (Test-ExactKeys -Object $updatedStrategyLibrary -Keys $strategyLibraryKeys)) {
    Restore-CommitteeFilesAndThrow "Committee changed the strategy library schema; the original committee-owned files were restored."
}
if ([string]$updatedStrategyLibrary._comment -ne [string]$originalStrategyLibrary._comment -or
    [string]$updatedStrategyLibrary.version -ne [string]$originalStrategyLibrary.version) {
    Restore-CommitteeFilesAndThrow "Committee changed immutable strategy library metadata; the original committee-owned files were restored."
}

$originalStrategyRevision = 0L
$updatedStrategyRevision = 0L
if (-not [long]::TryParse([string]$originalStrategyLibrary.revision, [ref]$originalStrategyRevision) -or
    -not [long]::TryParse([string]$updatedStrategyLibrary.revision, [ref]$updatedStrategyRevision) -or
    $originalStrategyRevision -lt 0 -or $updatedStrategyRevision -lt 0) {
    Restore-CommitteeFilesAndThrow "Committee wrote an invalid strategy library revision; the original committee-owned files were restored."
}

$strategyKeys = @(
    "strategy_id",
    "name",
    "status",
    "status_reason",
    "setup",
    "evidence_for",
    "evidence_against",
    "sample",
    "invalidation",
    "next_test",
    "created_central",
    "updated_central",
    "revision"
)
$sampleKeys = @(
    "phase_a_observations",
    "phase_b_cycles",
    "dry_run_orders",
    "live_orders",
    "closed_trades",
    "wins",
    "losses",
    "realized_pnl_usd"
)
$allowedStrategyStatuses = @("candidate", "observing", "dry_run_validated", "live_observing", "retired")
$updatedStrategies = @($updatedStrategyLibrary.strategies)
if ($updatedStrategies.Count -gt 100) {
    Restore-CommitteeFilesAndThrow "Committee wrote too many strategy records; the original committee-owned files were restored."
}
$strategyIds = @()
foreach ($strategy in $updatedStrategies) {
    $invalidNarrativeFields = @(@("status_reason", "setup", "invalidation", "next_test") | Where-Object {
        -not ($strategy.$_ -is [string]) -or ([string]$strategy.$_).Length -gt 600
    })
    if (-not (Test-ExactKeys -Object $strategy -Keys $strategyKeys) -or
        [string]$strategy.strategy_id -notmatch '^[a-z0-9]+(?:-[a-z0-9]+)*$' -or
        [string]$strategy.name -eq "" -or ([string]$strategy.name).Length -gt 120 -or
        [string]$strategy.status -notin $allowedStrategyStatuses -or
        $invalidNarrativeFields.Count -gt 0) {
        Restore-CommitteeFilesAndThrow "Committee wrote an invalid strategy record; the original committee-owned files were restored."
    }
    if (-not (Test-StringList -Value $strategy.evidence_for -MaxItems 12 -MaxLength 300) -or
        -not (Test-StringList -Value $strategy.evidence_against -MaxItems 12 -MaxLength 300) -or
        -not (Test-ExactKeys -Object $strategy.sample -Keys $sampleKeys)) {
        Restore-CommitteeFilesAndThrow "Committee wrote invalid strategy evidence or sample fields; the original committee-owned files were restored."
    }
    foreach ($sampleKey in @($sampleKeys | Where-Object { $_ -ne "realized_pnl_usd" })) {
        if (-not (Test-NonNegativeInteger -Value $strategy.sample.$sampleKey)) {
            Restore-CommitteeFilesAndThrow "Committee wrote an invalid strategy sample count; the original committee-owned files were restored."
        }
    }
    $realizedPnl = 0.0
    if (-not [double]::TryParse([string]$strategy.sample.realized_pnl_usd, [ref]$realizedPnl) -or
        [double]::IsNaN($realizedPnl) -or [double]::IsInfinity($realizedPnl) -or
        [long]$strategy.sample.wins + [long]$strategy.sample.losses -gt [long]$strategy.sample.closed_trades) {
        Restore-CommitteeFilesAndThrow "Committee wrote invalid strategy outcome statistics; the original committee-owned files were restored."
    }
    $strategyRevision = 0L
    if (-not [long]::TryParse([string]$strategy.revision, [ref]$strategyRevision) -or $strategyRevision -lt 1 -or
        -not ($strategy.created_central -is [string]) -or [string]::IsNullOrWhiteSpace($strategy.created_central) -or
        -not ($strategy.updated_central -is [string]) -or [string]::IsNullOrWhiteSpace($strategy.updated_central)) {
        Restore-CommitteeFilesAndThrow "Committee wrote invalid strategy revision metadata; the original committee-owned files were restored."
    }
    $strategyIds += [string]$strategy.strategy_id
}
if (@($strategyIds | Group-Object | Where-Object { $_.Count -gt 1 }).Count -gt 0) {
    Restore-CommitteeFilesAndThrow "Committee wrote duplicate strategy IDs; the original committee-owned files were restored."
}
$originalStrategyIds = @($originalStrategyLibrary.strategies | ForEach-Object { [string]$_.strategy_id })
if (@($originalStrategyIds | Where-Object { $_ -notin $strategyIds }).Count -gt 0) {
    Restore-CommitteeFilesAndThrow "Committee deleted a strategy instead of retiring it; the original committee-owned files were restored."
}

$evidenceKeys = @("evidence_id", "date_central", "strategy_id", "symbol", "phase", "verdict", "summary", "source_refs")
$allowedEvidencePhases = @("phase_a", "phase_b", "post_trade", "market_context")
$allowedEvidenceVerdicts = @("supports", "contradicts", "neutral")
$originalEvidence = @($originalStrategyLibrary.evidence_ledger)
$updatedEvidence = @($updatedStrategyLibrary.evidence_ledger)
if ($updatedEvidence.Count -lt $originalEvidence.Count -or $updatedEvidence.Count -gt $originalEvidence.Count + 12) {
    Restore-CommitteeFilesAndThrow "Committee violated the strategy evidence append limit; the original committee-owned files were restored."
}
for ($index = 0; $index -lt $originalEvidence.Count; $index++) {
    if (($updatedEvidence[$index] | ConvertTo-Json -Depth 20 -Compress) -ne
        ($originalEvidence[$index] | ConvertTo-Json -Depth 20 -Compress)) {
        Restore-CommitteeFilesAndThrow "Committee rewrote prior strategy evidence; the original committee-owned files were restored."
    }
}
$evidenceIds = @()
foreach ($evidence in $updatedEvidence) {
    if (-not (Test-ExactKeys -Object $evidence -Keys $evidenceKeys) -or
        [string]$evidence.evidence_id -notmatch '^[a-z0-9]+(?:-[a-z0-9]+)*$' -or
        [string]$evidence.strategy_id -notin $strategyIds -or
        -not ($evidence.date_central -is [string]) -or [string]::IsNullOrWhiteSpace($evidence.date_central) -or
        -not ($evidence.symbol -is [string]) -or ([string]$evidence.symbol).Length -gt 20 -or
        [string]$evidence.phase -notin $allowedEvidencePhases -or
        [string]$evidence.verdict -notin $allowedEvidenceVerdicts -or
        -not ($evidence.summary -is [string]) -or ([string]$evidence.summary).Length -gt 500 -or
        -not (Test-StringList -Value $evidence.source_refs -MaxItems 6 -MaxLength 500)) {
        Restore-CommitteeFilesAndThrow "Committee wrote an invalid strategy evidence entry; the original committee-owned files were restored."
    }
    $evidenceIds += [string]$evidence.evidence_id
}
if (@($evidenceIds | Group-Object | Where-Object { $_.Count -gt 1 }).Count -gt 0) {
    Restore-CommitteeFilesAndThrow "Committee wrote duplicate strategy evidence IDs; the original committee-owned files were restored."
}

$changeKeys = @("revision", "timestamp_central", "strategy_id", "action", "reason")
$allowedChangeActions = @("created", "updated", "promoted", "demoted", "retired", "evidence_added")
$originalChangeLog = @($originalStrategyLibrary.change_log)
$updatedChangeLog = @($updatedStrategyLibrary.change_log)
if ($updatedChangeLog.Count -lt $originalChangeLog.Count -or $updatedChangeLog.Count -gt $originalChangeLog.Count + 12) {
    Restore-CommitteeFilesAndThrow "Committee violated the strategy change-log append limit; the original committee-owned files were restored."
}
for ($index = 0; $index -lt $originalChangeLog.Count; $index++) {
    if (($updatedChangeLog[$index] | ConvertTo-Json -Depth 20 -Compress) -ne
        ($originalChangeLog[$index] | ConvertTo-Json -Depth 20 -Compress)) {
        Restore-CommitteeFilesAndThrow "Committee rewrote the strategy change history; the original committee-owned files were restored."
    }
}
foreach ($change in $updatedChangeLog) {
    if (-not (Test-ExactKeys -Object $change -Keys $changeKeys) -or
        -not (Test-NonNegativeInteger -Value $change.revision) -or [long]$change.revision -lt 1 -or
        [string]$change.strategy_id -notin $strategyIds -or
        [string]$change.action -notin $allowedChangeActions -or
        -not ($change.timestamp_central -is [string]) -or [string]::IsNullOrWhiteSpace($change.timestamp_central) -or
        -not ($change.reason -is [string]) -or ([string]$change.reason).Length -gt 500) {
        Restore-CommitteeFilesAndThrow "Committee wrote an invalid strategy change-log entry; the original committee-owned files were restored."
    }
}

$updatedStrategyLibraryJson = $updatedStrategyLibrary | ConvertTo-Json -Depth 100 -Compress
$strategyLibraryChanged = $updatedStrategyLibraryJson -ne $originalStrategyLibraryJson
if ($resolvedReviewMode -eq "intraday" -and $strategyLibraryChanged) {
    Restore-CommitteeFilesAndThrow "An intraday committee changed strategy_library.json; the original committee-owned files were restored."
}
if ($strategyLibraryChanged) {
    if ($updatedStrategyRevision -ne $originalStrategyRevision + 1 -or
        -not ($updatedStrategyLibrary.last_updated_central -is [string]) -or
        [string]::IsNullOrWhiteSpace($updatedStrategyLibrary.last_updated_central) -or
        $updatedEvidence.Count -eq $originalEvidence.Count -or
        $updatedChangeLog.Count -eq $originalChangeLog.Count) {
        Restore-CommitteeFilesAndThrow "Committee strategy changes lack a single revision, fresh evidence, or change history; the original committee-owned files were restored."
    }
}
elseif ($updatedStrategyRevision -ne $originalStrategyRevision) {
    Restore-CommitteeFilesAndThrow "Committee changed only the strategy revision; the original committee-owned files were restored."
}
elseif ($updatedStrategyLibraryText -ne $originalStrategyLibraryText) {
    [System.IO.File]::WriteAllText($strategyLibraryPath, $originalStrategyLibraryText, (New-Object System.Text.UTF8Encoding($false)))
}

try {
    $decision = Get-Content -Raw -Encoding UTF8 -LiteralPath $decisionPath | ConvertFrom-Json
}
catch {
    Restore-CommitteeFilesAndThrow "Committee decision JSON is invalid; the original committee-owned files were restored."
}

$requiredDecisionKeys = @(
    "date",
    "timestamp",
    "review_mode",
    "executive_decision",
    "run_phase_b",
    "personalization_updated",
    "personalization_revision",
    "daily_statistics_written",
    "strategy_library_updated",
    "strategy_library_revision",
    "proposal_symbols",
    "rationale",
    "report_path"
)
$actualDecisionKeys = @($decision.PSObject.Properties.Name)
if (@($actualDecisionKeys | Where-Object { $_ -notin $requiredDecisionKeys }).Count -gt 0 -or
    @($requiredDecisionKeys | Where-Object { $_ -notin $actualDecisionKeys }).Count -gt 0) {
    Restore-CommitteeFilesAndThrow "Committee decision JSON has the wrong schema; the original committee-owned files were restored."
}
if (-not ($decision.run_phase_b -is [bool]) -or
    -not ($decision.personalization_updated -is [bool]) -or
    -not ($decision.daily_statistics_written -is [bool]) -or
    -not ($decision.strategy_library_updated -is [bool])) {
    Restore-CommitteeFilesAndThrow "Committee decision booleans are invalid; the original committee-owned files were restored."
}
$decisionPersonalizationRevision = 0L
$decisionStrategyLibraryRevision = 0L
$proposalSymbols = @($decision.proposal_symbols)
if (-not [long]::TryParse([string]$decision.personalization_revision, [ref]$decisionPersonalizationRevision) -or
    -not [long]::TryParse([string]$decision.strategy_library_revision, [ref]$decisionStrategyLibraryRevision) -or
    $decisionPersonalizationRevision -lt 0 -or $decisionStrategyLibraryRevision -lt 0 -or
    -not ($decision.date -is [string]) -or [string]$decision.date -notmatch '^\d{4}-\d{2}-\d{2}$' -or
    -not ($decision.timestamp -is [string]) -or [string]$decision.timestamp -notmatch '^\d{2}:\d{2}:\d{2}$' -or
    -not ($decision.review_mode -is [string]) -or [string]$decision.review_mode -notin @("intraday", "end_of_day") -or
    -not ($decision.executive_decision -is [string]) -or [string]$decision.executive_decision -notin @("run_phase_b", "skip_phase_b") -or
    -not ($decision.rationale -is [string]) -or [string]::IsNullOrWhiteSpace([string]$decision.rationale) -or ([string]$decision.rationale).Length -gt 1200 -or
    -not ($decision.report_path -is [string]) -or [string]::IsNullOrWhiteSpace([string]$decision.report_path) -or
    $decision.proposal_symbols -is [string] -or $proposalSymbols.Count -gt 50 -or
    @($proposalSymbols | Where-Object { -not ($_ -is [string]) -or $_ -notmatch '^[A-Z][A-Z0-9.-]{0,9}$' }).Count -gt 0) {
    Restore-CommitteeFilesAndThrow "Committee decision values are invalid; the original committee-owned files were restored."
}
if (($decision.run_phase_b -and $decision.executive_decision -ne "run_phase_b") -or
    (-not $decision.run_phase_b -and $decision.executive_decision -ne "skip_phase_b")) {
    Restore-CommitteeFilesAndThrow "Committee decision fields disagree; the original committee-owned files were restored."
}
if ([string]$decision.review_mode -ne $resolvedReviewMode -or
    [bool]$decision.daily_statistics_written -ne ($resolvedReviewMode -eq "end_of_day")) {
    Restore-CommitteeFilesAndThrow "Committee decision does not match the requested review mode; the original committee-owned files were restored."
}

$updatedPersonalizationJson = $updatedRiskRules.personalization | ConvertTo-Json -Depth 20 -Compress
$personalizationChanged = $updatedPersonalizationJson -ne $originalPersonalizationJson
if ([bool]$decision.personalization_updated -ne $personalizationChanged -or
    $decisionPersonalizationRevision -ne $updatedRevision) {
    Restore-CommitteeFilesAndThrow "Committee decision does not match the personalization update; the original committee-owned files were restored."
}
if ([bool]$decision.strategy_library_updated -ne $strategyLibraryChanged -or
    $decisionStrategyLibraryRevision -ne $updatedStrategyRevision) {
    Restore-CommitteeFilesAndThrow "Committee decision does not match the strategy library update; the original committee-owned files were restored."
}
try {
    $decisionReportPath = [System.IO.Path]::GetFullPath([string]$decision.report_path)
}
catch {
    Restore-CommitteeFilesAndThrow "Committee decision contains an invalid report path; the original committee-owned files were restored."
}
if ($decisionReportPath -ne [System.IO.Path]::GetFullPath($reportPath)) {
    Restore-CommitteeFilesAndThrow "Committee decision references the wrong report path; the original committee-owned files were restored."
}

Write-Output ("run_phase_b=" + ([bool]$decision.run_phase_b).ToString().ToLowerInvariant())
Write-Output ("personalization_updated=" + $personalizationChanged.ToString().ToLowerInvariant())
Write-Output ("review_mode=" + $resolvedReviewMode)
Write-Output ("daily_statistics_written=" + ([bool]$decision.daily_statistics_written).ToString().ToLowerInvariant())
Write-Output ("strategy_library_updated=" + $strategyLibraryChanged.ToString().ToLowerInvariant())
Write-Output ("strategy_library_revision=" + $updatedStrategyRevision)
$opusStatus = "not_triggered"
$opusConsulted = $false
if (Test-Path -LiteralPath $opusResultPath -PathType Leaf) {
    try {
        $opusResult = Get-Content -Raw -Encoding UTF8 -LiteralPath $opusResultPath | ConvertFrom-Json
        $opusStatus = [string]$opusResult.status
        $opusConsulted = $opusStatus -eq "completed"
    }
    catch {
        $opusStatus = "invalid_result"
    }
}
elseif (Test-Path -LiteralPath $opusRequestPath -PathType Leaf) {
    $opusStatus = if ($opusAvailable) { "failed" } else { "unavailable" }
}
Write-Output ("opus_status=" + $opusStatus)
Write-Output ("opus_consulted=" + $opusConsulted.ToString().ToLowerInvariant())
if (Test-Path -LiteralPath $opusResultPath -PathType Leaf) {
    Write-Output ("opus_consultation=" + $opusResultPath)
}
$freeNewsStatus = "disabled"
$freeNewsCompleted = $false
$freeNewsProvider = "none"
$freeNewsFallbackUsed = $false
$freeNewsCommitteeFallbackAgents = 0
if ($FreeNewsDesk -eq "on") {
    $freeNewsStatus = "not_run"
}
if (Test-Path -LiteralPath $freeNewsResultPath -PathType Leaf) {
    try {
        $freeNewsResult = Get-Content -Raw -Encoding UTF8 -LiteralPath $freeNewsResultPath | ConvertFrom-Json
        $freeNewsStatus = [string]$freeNewsResult.status
        $freeNewsCompleted = $freeNewsStatus -in @("completed", "partial")
        $freeNewsProvider = [string]$freeNewsResult.provider
        if ($null -ne $freeNewsResult.fallback -and $freeNewsResult.fallback.used -is [bool]) {
            $freeNewsFallbackUsed = [bool]$freeNewsResult.fallback.used
        }
        $parsedCommitteeFallbackAgents = 0L
        if ($null -ne $freeNewsResult.fallback -and
            [long]::TryParse([string]$freeNewsResult.fallback.deferred_to_committee, [ref]$parsedCommitteeFallbackAgents) -and
            $parsedCommitteeFallbackAgents -ge 0) {
            $freeNewsCommitteeFallbackAgents = $parsedCommitteeFallbackAgents
        }
    }
    catch {
        $freeNewsStatus = "invalid_result"
    }
}
elseif ($FreeNewsDesk -eq "on" -and (Test-Path -LiteralPath $freeNewsPacketPath -PathType Leaf)) {
    $freeNewsStatus = "unavailable"
}
Write-Output ("free_news_status=" + $freeNewsStatus)
Write-Output ("free_news_completed=" + $freeNewsCompleted.ToString().ToLowerInvariant())
Write-Output ("free_news_provider=" + $freeNewsProvider)
Write-Output ("free_news_fallback_used=" + $freeNewsFallbackUsed.ToString().ToLowerInvariant())
Write-Output ("free_news_fallback_model=" + $FreeNewsFallbackModel)
Write-Output ("free_news_committee_fallback_agents=" + $freeNewsCommitteeFallbackAgents)
if (Test-Path -LiteralPath $freeNewsResultPath -PathType Leaf) {
    Write-Output ("free_news_result=" + $freeNewsResultPath)
}
Write-Output ("committee_report=" + $reportPath)
Write-Output ("committee_decision=" + $decisionPath)
