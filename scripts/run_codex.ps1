[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("A", "B")]
    [string]$Phase,

    [string]$Model,

    [switch]$Preview
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$phaseLower = $Phase.ToLowerInvariant()
$promptPath = Join-Path $repoRoot "prompts\phase_$phaseLower.md"
$riskRulesPath = Join-Path $repoRoot "risk_rules.json"
$privateConfigPath = if (-not [string]::IsNullOrWhiteSpace($env:FRIESTRADER_PRIVATE_CONFIG)) {
    $env:FRIESTRADER_PRIVATE_CONFIG
}
else {
    Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex\state\friestrader\local.json"
}

if (-not (Test-Path -LiteralPath $promptPath -PathType Leaf)) {
    throw "Prompt file not found: $promptPath"
}

$codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
if ($null -eq $codexCommand) {
    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
}
if ($null -eq $codexCommand) {
    throw "Codex CLI was not found on PATH. Install it and run 'codex login' first."
}
$codexCommandPath = [System.IO.Path]::GetFullPath([string]$codexCommand.Source)

$codexArgs = @(
    "-C", $repoRoot,
    "-a", "never",
    "-s", "workspace-write",
    "-c", "sandbox_workspace_write.network_access=true",
    "-c", "mcp_servers.robinhood-trading.required=true",
    "--search"
)

if ($Phase -eq "B") {
    # Phase B is an unattended workflow. Pre-authorize Robinhood MCP tool
    # calls so review_equity_order can run without an interactive prompt.
    # This does not bypass the sandbox and does not change the task's
    # execution.mode/live-order gate; place_equity_order remains governed by
    # PHASE_B_TASK.md and risk_rules.json.
    $codexArgs += @(
        "-c", 'mcp_servers.robinhood-trading.default_tools_approval_mode="approve"'
    )
}

if (-not [string]::IsNullOrWhiteSpace($Model)) {
    $codexArgs += @("-m", $Model)
}

$codexArgs += @("exec", "--ephemeral", "--color", "never", "-")

if ($Preview) {
    $displayArgs = $codexArgs | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"' + $_.Replace('"', '\"') + '"'
        }
        else {
            $_
        }
    }

    Write-Output ("codex " + ($displayArgs -join " "))
    Write-Output ("stdin: " + $promptPath)
    exit 0
}

if (-not (Test-Path -LiteralPath $riskRulesPath -PathType Leaf)) {
    throw "risk_rules.json not found: $riskRulesPath"
}

$riskRules = Get-Content -Raw -Encoding UTF8 -LiteralPath $riskRulesPath | ConvertFrom-Json
$unsetValues = @()
$privateConfig = $null

if (Test-Path -LiteralPath $privateConfigPath -PathType Leaf) {
    $privateConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $privateConfigPath | ConvertFrom-Json
}

$runtimeAccountNumber = [string]$riskRules.account_number
if ($runtimeAccountNumber -match '^YOUR_.*_HERE$' -and $null -ne $privateConfig) {
    $runtimeAccountNumber = [string]$privateConfig.account_number
}

$runtimeLinkedAccounts = @($riskRules.wash_sale_avoidance.linked_accounts | ForEach-Object { [string]$_ })
if (@($runtimeLinkedAccounts | Where-Object { $_ -match '^YOUR_.*_HERE$' }).Count -gt 0 -and $null -ne $privateConfig) {
    $runtimeLinkedAccounts = @($privateConfig.linked_accounts | ForEach-Object { [string]$_ })
}

if ([string]::IsNullOrWhiteSpace($runtimeAccountNumber) -or $runtimeAccountNumber -match '^YOUR_.*_HERE$') {
    $unsetValues += "account_number"
}
if ($runtimeLinkedAccounts.Count -eq 0 -or @($runtimeLinkedAccounts | Where-Object { [string]::IsNullOrWhiteSpace($_) -or $_ -match '^YOUR_.*_HERE$' }).Count -gt 0) {
    $unsetValues += "wash_sale_avoidance.linked_accounts"
}
if ([string]$riskRules.universe.watchlist_name -match '^YOUR_.*_HERE$') {
    $unsetValues += "universe.watchlist_name"
}
if ([string]$riskRules.universe.supplementary_scan_id -match '^YOUR_.*_HERE$') {
    $unsetValues += "universe.supplementary_scan_id"
}

if ($unsetValues.Count -gt 0) {
    throw "Configure these risk_rules.json values before running: $($unsetValues -join ', ')"
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

$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $gitCommand) {
    throw "Git was not found on PATH."
}

function Invoke-FriesTraderGit {
    param([Parameter(Mandatory = $true)][string[]]$GitArguments)

    $savedGitErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $gitOutput = @(& $gitCommand.Source -C $repoRoot @GitArguments 2>&1)
        $gitExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedGitErrorActionPreference
    }
    if ($gitExitCode -ne 0) {
        throw "git $($GitArguments -join ' ') failed:`n$($gitOutput -join [Environment]::NewLine)"
    }
    return $gitOutput
}

$initialStagedFiles = @(Invoke-FriesTraderGit -GitArguments @("diff", "--cached", "--name-only"))
if ($initialStagedFiles.Count -gt 0) {
    throw "The Git staging area must be empty before a FriesTrader run. Staged files: $($initialStagedFiles -join ', ')"
}

$logsPath = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null

$centralTimeZone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
$centralNow = [System.TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $centralTimeZone)
$logPath = Join-Path $logsPath ("codex-phase-{0}-{1}.log" -f $phaseLower, $centralNow.ToString("yyyyMMdd-HHmmss"))
$prompt = Get-Content -Raw -Encoding UTF8 -LiteralPath $promptPath
$prompt = $prompt.Replace("<your Robinhood account_number>", $runtimeAccountNumber)
$runtimeOverrides = [ordered]@{
    account_number = $runtimeAccountNumber
    wash_sale_avoidance = [ordered]@{
        linked_accounts = $runtimeLinkedAccounts
    }
} | ConvertTo-Json -Depth 4 -Compress
$prompt += @"

PRIVATE RUNTIME OVERRIDES
The tracked risk_rules.json intentionally keeps account placeholders because this is a public repository. For this run only, treat the following JSON as authoritative for those placeholder fields. Do not print, log, commit, or persist the full account numbers anywhere:
$runtimeOverrides
"@
$prompt += @"

WINDOWS RUNTIME NOTE
For every Bash command required by the task, use C:\msys64\usr\bin\bash.exe. This is the installed Bash executable that honors TZ=America/Chicago in this environment. Do not use WSL bash or Git for Windows bash for those time commands.
"@
$prompt += @"

WINDOWS GIT NOTE
The workspace-write sandbox intentionally protects the checkout's .git directory. Attempt the task's requested Git commands once. If Git reports that .git/index.lock is denied, do not use a GitHub connector or create a temporary clone; leave the validated output file in this checkout and finish normally. The launcher will then perform the same narrowly scoped add, commit, and push outside the AI sandbox.
"@

$sensitiveAccountNumbers = @($runtimeAccountNumber) + $runtimeLinkedAccounts |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_ -notmatch '^YOUR_.*_HERE$' } |
    Sort-Object -Unique

Write-Host "Starting FriesTrader Phase $Phase with Codex CLI."
Write-Host "Combined run log: $logPath"

$previousGitConfigCount = [Environment]::GetEnvironmentVariable("GIT_CONFIG_COUNT", "Process")
$previousPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
$msysBashDirectory = "C:\msys64\usr\bin"
if (-not (Test-Path -LiteralPath (Join-Path $msysBashDirectory "bash.exe") -PathType Leaf)) {
    throw "Required Bash executable not found: $msysBashDirectory\bash.exe"
}
[Environment]::SetEnvironmentVariable("PATH", "$msysBashDirectory;$previousPath", "Process")
$gitConfigIndex = if ([string]::IsNullOrWhiteSpace($previousGitConfigCount)) { 0 } else { [int]$previousGitConfigCount }
$gitConfigKeyName = "GIT_CONFIG_KEY_$gitConfigIndex"
$gitConfigValueName = "GIT_CONFIG_VALUE_$gitConfigIndex"
$previousGitConfigKey = [Environment]::GetEnvironmentVariable($gitConfigKeyName, "Process")
$previousGitConfigValue = [Environment]::GetEnvironmentVariable($gitConfigValueName, "Process")
[Environment]::SetEnvironmentVariable($gitConfigKeyName, "safe.directory", "Process")
[Environment]::SetEnvironmentVariable($gitConfigValueName, $repoRoot.Replace('\', '/'), "Process")
[Environment]::SetEnvironmentVariable("GIT_CONFIG_COUNT", [string]($gitConfigIndex + 1), "Process")

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
    } | Tee-Object -FilePath $logPath
    $codexExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $savedErrorActionPreference
    [Environment]::SetEnvironmentVariable("PATH", $previousPath, "Process")
    [Environment]::SetEnvironmentVariable($gitConfigKeyName, $previousGitConfigKey, "Process")
    [Environment]::SetEnvironmentVariable($gitConfigValueName, $previousGitConfigValue, "Process")
    [Environment]::SetEnvironmentVariable("GIT_CONFIG_COUNT", $previousGitConfigCount, "Process")
}

if ($codexExitCode -ne 0) {
    throw "Codex CLI exited with code $codexExitCode. See $logPath"
}

[string[]]$outputFileNames = if ($Phase -eq "A") {
    @("pending_proposals.jsonl")
}
else {
    @("trade_log.jsonl", "trade_log_recent.md")
}
$outputFileName = $outputFileNames[0]
$outputFilePath = Join-Path $repoRoot $outputFileName
foreach ($requiredOutputFileName in $outputFileNames) {
    $requiredOutputPath = Join-Path $repoRoot $requiredOutputFileName
    if (-not (Test-Path -LiteralPath $requiredOutputPath -PathType Leaf)) {
        throw "Codex completed without producing the required output file: $requiredOutputPath"
    }
}

if ($Phase -eq "A") {
    $validatorPath = Join-Path $scriptRoot "validate_phase_a.py"
    if (-not (Test-Path -LiteralPath $validatorPath -PathType Leaf)) {
        throw "Phase A validator not found: $validatorPath"
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        $pythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if ($null -eq $pythonCommand) {
        throw "Python was not found on PATH; cannot validate the Phase A handoff."
    }

    & $pythonCommand.Source -X utf8 $validatorPath $outputFilePath
    $validatorExitCode = $LASTEXITCODE
    if ($validatorExitCode -ne 0) {
        throw "Phase A output failed contract validation with code $validatorExitCode. Refusing to stage, commit, or continue."
    }
}

$outputStatusArguments = @("status", "--porcelain", "--") + $outputFileNames
$outputStatus = @(Invoke-FriesTraderGit -GitArguments $outputStatusArguments)
if ($outputStatus.Count -gt 0) {
    $stagedFiles = @(Invoke-FriesTraderGit -GitArguments @("diff", "--cached", "--name-only"))
    $unexpectedStagedFiles = @($stagedFiles | Where-Object { $_ -notin $outputFileNames })
    if ($unexpectedStagedFiles.Count -gt 0) {
        throw "Refusing to commit unexpected staged files: $($unexpectedStagedFiles -join ', ')"
    }

    $addArguments = @("add", "--") + $outputFileNames
    Invoke-FriesTraderGit -GitArguments $addArguments | Out-Null
    $stagedFiles = @(Invoke-FriesTraderGit -GitArguments @("diff", "--cached", "--name-only"))
    $unexpectedStagedFiles = @($stagedFiles | Where-Object { $_ -notin $outputFileNames })
    if ($unexpectedStagedFiles.Count -gt 0 -or $outputFileName -notin $stagedFiles) {
        throw "Expected only changed Phase $Phase outputs to be staged, including $outputFileName; found: $($stagedFiles -join ', ')"
    }

    $jsonRows = @(Get-Content -Encoding UTF8 -LiteralPath $outputFilePath |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_ | ConvertFrom-Json })
    if ($jsonRows.Count -eq 0) {
        throw "$outputFileName contains no JSON records."
    }
    $commitMetadata = $jsonRows[-1]
    if ([string]::IsNullOrWhiteSpace([string]$commitMetadata.date) -or [string]::IsNullOrWhiteSpace([string]$commitMetadata.timestamp)) {
        throw "The final $outputFileName record is missing date or timestamp."
    }

    $commitMessage = "Phase $Phase run $($commitMetadata.date) $($commitMetadata.timestamp)"
    Invoke-FriesTraderGit -GitArguments @("commit", "-m", $commitMessage) | ForEach-Object { Write-Host $_ }
}

Invoke-FriesTraderGit -GitArguments @("push", "origin", "main") | ForEach-Object { Write-Host $_ }
$finalCommit = [string](Invoke-FriesTraderGit -GitArguments @("rev-parse", "HEAD"))
Write-Host "FriesTrader Phase $Phase output is committed and pushed: $finalCommit"
