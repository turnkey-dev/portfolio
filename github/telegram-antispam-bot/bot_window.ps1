param([switch]$SmokeTest)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
Set-Location -LiteralPath $PSScriptRoot

$script:botProcess = $null
$script:readers = @()
$script:stopping = $false
$script:connected = $false
$script:configPath = Join-Path $PSScriptRoot '.env'
if ($SmokeTest) {
    $script:configPath = Join-Path ([IO.Path]::GetTempPath()) ('bot-gui-test-' + [guid]::NewGuid() + '.env')
    [IO.File]::WriteAllText($script:configPath, "BOT_TOKEN=test-placeholder`r`nDRY_RUN=true`r`nALLOWED_CHAT_IDS=-100123`r`n")
}

function Convert-ChatIds([string]$value) {
    $parts = @($value.Trim() -split '[,;\s]+' | Where-Object { $_ })
    if ($parts.Count -eq 0) { throw 'Вставьте ID группы или выберите «Все группы бота».' }
    $result = @()
    foreach ($part in $parts) {
        [long]$number = 0
        if ($part -notmatch '^-[1-9][0-9]*$' -or -not [long]::TryParse($part, [ref]$number)) {
            throw 'ID группы — отрицательное число, например -1001234567890. Получите его командой /chatid@your_bot в группе.'
        }
        if ($number -lt -4503599627370495) { throw 'Слишком длинный ID группы. Проверьте число.' }
        if ($result -notcontains $part) { $result += $part }
    }
    return ($result -join ',')
}

function Save-ChatSettings {
    if ($script:botProcess -and -not $script:botProcess.HasExited) { throw 'Сначала остановите бота, затем сохраните группы.' }
    $value = if ($allChats.Checked) { '' } else { Convert-ChatIds $chatIds.Text }
    if (-not (Test-Path -LiteralPath $script:configPath)) { throw 'Не найден файл .env с токеном бота.' }
    $text = [IO.File]::ReadAllText($script:configPath)
    $pattern = '(?m)^\s*ALLOWED_CHAT_IDS\s*=[^\r\n]*'
    if ([regex]::IsMatch($text, $pattern)) {
        $text = [regex]::Replace($text, $pattern, ('ALLOWED_CHAT_IDS=' + $value))
    } else { $text = $text.TrimEnd() + "`r`nALLOWED_CHAT_IDS=$value`r`n" }
    $temporary = $script:configPath + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary, $text, [Text.UTF8Encoding]::new($false))
        [IO.File]::Replace($temporary, $script:configPath, [NullString]::Value)
    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
    $chatIds.Text = $value
    $scopeStatus.Text = if ($allChats.Checked) { 'Сохранено: все группы, куда добавлен бот.' } else { 'Сохранено групп: ' + @($value -split ',').Count }
    Say $scopeStatus.Text
}

function Set-SettingsEnabled([bool]$enabled) {
    $allChats.Enabled = $enabled
    $chatIds.Enabled = $enabled -and -not $allChats.Checked
    $saveChats.Enabled = $enabled
}

function Protect-Log([string]$line) {
    return [regex]::Replace($line, '\d{6,}:[A-Za-z0-9_-]{20,}', '[TOKEN]')
}

function Get-FriendlyLog([string]$line) {
    if ($line -match 'Бот @.+ запущен') { return 'Подключение к Telegram установлено. Бот проверяет новые сообщения.' }
    if ($line -match '\bTEST\b') { return 'Замечен спам. Тестовый режим: сообщение оставлено, участник не заблокирован.' }
    if ($line -match 'OK deleteMessage') { return 'Спам-сообщение удалено.' }
    if ($line -match 'OK banChatMember') { return 'Отправитель спама заблокирован.' }
    if ($line -match 'FAIL deleteMessage') { return 'Не удалось удалить сообщение. Проверьте права бота; подробности во вкладке технических логов.' }
    if ($line -match 'FAIL banChatMember') { return 'Не удалось заблокировать участника. Проверьте права бота; подробности во вкладке технических логов.' }
    if ($line -match 'Другой экземпляр') { return 'Бот уже работает в другом окне. Сначала остановите его там.' }
    if ($line -match 'Нет соединения|Повтор после ошибки') { return 'Временная ошибка связи с Telegram. Бот попробует снова.' }
    if ($line -match 'Не удалось запустить бота:') { return ($line -replace '^.*Не удалось запустить бота:', 'Запуск не удался:') }
    if ($line -match 'Остановка:') { return 'Telegram остановил работу. Проверьте токен и закройте другие запуски бота.' }
    if ($line -match 'ERROR|Traceback|Exception') { return 'Произошла ошибка. Подробности доступны во вкладке технических логов.' }
    return $null
}

function Add-Line($box, [string]$line) {
    if ($box.TextLength -gt 180000) { $box.Text = $box.Text.Substring(90000) }
    $box.AppendText($line + [Environment]::NewLine)
    $box.SelectionStart = $box.TextLength
    $box.ScrollToCaret()
}
function Say([string]$line) { Add-Line $humanBox ((Get-Date -Format 'HH:mm:ss') + '  ' + $line) }

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Антиспам · управление ботом'
$form.Size = New-Object System.Drawing.Size(900, 815)
$form.MinimumSize = New-Object System.Drawing.Size(900, 680)
$form.StartPosition = 'CenterScreen'
$form.BackColor = [System.Drawing.Color]::FromArgb(244, 247, 251)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Защита группы Telegram'
$title.Font = New-Object System.Drawing.Font('Segoe UI', 19, [System.Drawing.FontStyle]::Bold)
$title.SetBounds(24, 18, 800, 42)
$form.Controls.Add($title)
$status = New-Object System.Windows.Forms.Label
$status.SetBounds(26, 67, 800, 26)
$status.Text = 'Остановлен'
$form.Controls.Add($status)
$mode = New-Object System.Windows.Forms.Label
$mode.SetBounds(26, 98, 800, 26)
$form.Controls.Add($mode)

function Update-Mode {
    $mode.Text = 'Режим: удаление спама и бессрочный бан'
    if (Test-Path -LiteralPath '.env') {
        $config = Get-Content -LiteralPath '.env' -Encoding UTF8
        if ($config -match '^\s*DRY_RUN\s*=\s*["'']?true') {
            $mode.Text = 'Тестовый режим: без удаления сообщений и банов'
        }
    } else { $mode.Text = 'Сначала заполните файл .env с токеном бота' }
}
Update-Mode

$startButton = New-Object System.Windows.Forms.Button
$startButton.Text = 'Запустить бота'
$startButton.SetBounds(26, 139, 200, 45)
$startButton.BackColor = [System.Drawing.Color]::FromArgb(35, 113, 220)
$startButton.ForeColor = [System.Drawing.Color]::White
$startButton.FlatStyle = 'Flat'
$form.Controls.Add($startButton)
$stopButton = New-Object System.Windows.Forms.Button
$stopButton.Text = 'Остановить бота'
$stopButton.SetBounds(240, 139, 200, 45)
$stopButton.Enabled = $false
$form.Controls.Add($stopButton)

$chatLabel = New-Object System.Windows.Forms.Label
$chatLabel.Text = 'Группы для проверки — вставьте ID через запятую или каждый с новой строки'
$chatLabel.SetBounds(26, 202, 820, 25)
$form.Controls.Add($chatLabel)
$chatIds = New-Object System.Windows.Forms.TextBox
$chatIds.Multiline = $true
$chatIds.ScrollBars = 'Vertical'
$chatIds.SetBounds(26, 232, 610, 57)
$chatIds.Anchor = 'Top, Left, Right'
$form.Controls.Add($chatIds)
$saveChats = New-Object System.Windows.Forms.Button
$saveChats.Text = 'Сохранить группы'
$saveChats.SetBounds(650, 232, 208, 38)
$saveChats.Anchor = 'Top, Right'
$form.Controls.Add($saveChats)
$allChats = New-Object System.Windows.Forms.CheckBox
$allChats.Text = 'Все группы бота (без ограничения по ID)'
$allChats.SetBounds(26, 294, 620, 25)
$form.Controls.Add($allChats)
$scopeStatus = New-Object System.Windows.Forms.Label
$scopeStatus.SetBounds(26, 321, 820, 25)
$scopeStatus.Text = 'Узнать ID: отправьте /chatid@your_bot в нужной группе при работающем боте.'
$form.Controls.Add($scopeStatus)
if (Test-Path -LiteralPath $script:configPath) {
    $entry = Get-Content -LiteralPath $script:configPath -Encoding UTF8 | Where-Object { $_ -match '^\s*ALLOWED_CHAT_IDS\s*=' } | Select-Object -First 1
    $chatIds.Text = if ($entry) { ($entry -split '=', 2)[1].Trim().Trim('"', "'") } else { '' }
    $allChats.Checked = [string]::IsNullOrWhiteSpace($chatIds.Text)
}
$chatIds.Enabled = -not $allChats.Checked
$allChats.Add_CheckedChanged({ $chatIds.Enabled = -not $allChats.Checked })
$saveChats.Add_Click({
    try { Save-ChatSettings }
    catch { Say ('Группы не сохранены: ' + $_.Exception.Message) }
})

$tabs = New-Object System.Windows.Forms.TabControl
$tabs.SetBounds(24, 375, 835, 345)
$tabs.Anchor = 'Top, Bottom, Left, Right'
$form.Controls.Add($tabs)
$humanTab = New-Object System.Windows.Forms.TabPage
$humanTab.Text = 'Что происходит'
$technicalTab = New-Object System.Windows.Forms.TabPage
$technicalTab.Text = 'Технические логи'
$tabs.TabPages.Add($humanTab)
$tabs.TabPages.Add($technicalTab)
function New-LogBox($tab) {
    $box = New-Object System.Windows.Forms.RichTextBox
    $box.Dock = 'Fill'
    $box.ReadOnly = $true
    $box.BackColor = [System.Drawing.Color]::White
    $box.BorderStyle = 'None'
    $box.Font = New-Object System.Drawing.Font('Segoe UI', 11)
    $tab.Controls.Add($box)
    return $box
}
$humanBox = New-LogBox $humanTab
$technicalBox = New-LogBox $technicalTab
$technicalBox.Font = New-Object System.Drawing.Font('Consolas', 10)
$foot = New-Object System.Windows.Forms.Label
$foot.Text = 'Закрытие окна останавливает бота. История действий сохраняется в data\moderation.log.'
$foot.SetBounds(24, 739, 835, 28)
$foot.Anchor = 'Bottom, Left, Right'
$form.Controls.Add($foot)

function Read-Output {
    foreach ($reader in $script:readers) {
        while ($null -ne ($line = $reader.ReadLine())) {
            $line = Protect-Log $line
            Add-Line $technicalBox $line
            $friendly = Get-FriendlyLog $line
            if ($friendly) { Say $friendly }
            if ($line -match 'Бот @.+ запущен') {
                $script:connected = $true
                $status.Text = 'Работает · подключён к Telegram'
            } elseif ($line -match 'Повтор после ошибки') {
                $status.Text = 'Работает · повторяет запрос к Telegram'
            }
        }
    }
}
function Close-Readers {
    foreach ($reader in $script:readers) { $reader.Dispose() }
    $script:readers = @()
}

$startButton.Add_Click({
    if ($script:botProcess -and -not $script:botProcess.HasExited) { return }
    try {
        Save-ChatSettings
        Update-Mode
        $script:connected = $false
        $script:stopping = $false
        $python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        $arguments = @('-u', ('"' + (Join-Path $PSScriptRoot 'bot.py') + '"'))
        if (-not (Test-Path -LiteralPath $python)) {
            $command = Get-Command python -ErrorAction SilentlyContinue
            if (-not $command) {
                $command = Get-Command py -ErrorAction SilentlyContinue
                $arguments = @('-3') + $arguments
            }
            if (-not $command) { throw 'Не найден Python. Установите Python 3.10 или новее.' }
            $python = $command.Source
        }
        if ($SmokeTest) {
            $arguments = @('-u', '-c', '"import time; print(''OK deleteMessage'', flush=True); time.sleep(30)"')
        }
        New-Item -ItemType Directory -Path 'data' -Force | Out-Null
        Close-Readers
        $env:PYTHONIOENCODING = 'utf-8'
        $script:botProcess = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput 'data\window.stdout.log' -RedirectStandardError 'data\window.stderr.log' -PassThru
        foreach ($file in @('data\window.stdout.log', 'data\window.stderr.log')) {
            $stream = [IO.File]::Open((Join-Path $PSScriptRoot $file), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
            $script:readers += [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8)
        }
        $startButton.Enabled = $false
        $stopButton.Enabled = $true
        Set-SettingsEnabled $false
        $status.Text = 'Запускается · подключение к Telegram…'
        Say 'Запускаю бота. Ожидаю подтверждения подключения к Telegram.'
    } catch {
        Say ('Не удалось запустить: ' + (Protect-Log $_.Exception.Message))
        if ($script:botProcess -and -not $script:botProcess.HasExited) { $script:botProcess.Kill() }
        Close-Readers
        $status.Text = 'Ошибка запуска'
        $startButton.Enabled = $true
        $stopButton.Enabled = $false
        Set-SettingsEnabled $true
    }
})

$stopButton.Add_Click({
    if ($script:botProcess -and -not $script:botProcess.HasExited) {
        try {
            $script:stopping = $true
            $script:botProcess.Kill()
            $status.Text = 'Останавливается…'
            $stopButton.Enabled = $false
            Set-SettingsEnabled $true
        } catch { Say ('Не удалось остановить: ' + $_.Exception.Message) }
    }
})
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 300
$timer.Add_Tick({
    if ($script:botProcess) {
        Read-Output
        if ($script:botProcess.HasExited) {
            Read-Output
            Close-Readers
            $code = $script:botProcess.ExitCode
            if ($script:stopping) { Say 'Бот остановлен. Новые сообщения больше не проверяются.' }
            else { Say "Процесс бота завершился (код $code). Если это неожиданно, посмотрите технические логи." }
            $status.Text = 'Остановлен'
            $startButton.Enabled = $true
            $stopButton.Enabled = $false
            $script:botProcess.Dispose()
            $script:botProcess = $null
        }
    }
})
$form.Add_FormClosing({
    if ($script:botProcess -and -not $script:botProcess.HasExited) {
        try { $script:botProcess.Kill(); $script:botProcess.WaitForExit(5000) | Out-Null }
        catch { $_.Cancel = $true; Say 'Не удалось остановить бота. Нажмите «Остановить бота» перед закрытием.'; return }
    }
    $timer.Stop()
    Close-Readers
})
Say 'Нажмите «Запустить бота». В этом окне появятся результаты проверки сообщений.'
Say 'Обычные сообщения в журнал не записываются. Если спама нет, журнал может оставаться без изменений.'

if ($SmokeTest) {
    if ((Convert-ChatIds "-100123, -100456`r`n-100123; -789") -ne '-100123,-100456,-789') { throw 'Multiple IDs failed' }
    foreach ($invalid in @('', '123', '@group', '-100x', '-999999999999999999999')) {
        $rejected = $false
        try { Convert-ChatIds $invalid | Out-Null } catch { $rejected = $true }
        if (-not $rejected) { throw 'Invalid ID accepted' }
    }
    $allChats.Checked = $false
    $chatIds.Text = "-100123`r`n-100456"
    Save-ChatSettings
    $saved = [IO.File]::ReadAllText($script:configPath)
    if ($saved -notmatch 'ALLOWED_CHAT_IDS=-100123,-100456' -or $saved -notmatch 'BOT_TOKEN=test-placeholder' -or $saved -notmatch 'DRY_RUN=true') { throw 'Save/preservation failed' }
    $allChats.Checked = $true
    Save-ChatSettings
    if ([IO.File]::ReadAllText($script:configPath) -notmatch 'ALLOWED_CHAT_IDS=\r?\n') { throw 'All groups save failed' }
    if ((Get-FriendlyLog 'OK deleteMessage') -ne 'Спам-сообщение удалено.') { throw 'Translation failed' }
    if ((Protect-Log '123456789:abcdefghijklmnopqrstuvwxyz') -ne '[TOKEN]') { throw 'Redaction failed' }
    if ($stopButton.Enabled -or -not $startButton.Enabled) { throw 'Initial state failed' }
    $form.Show()
    [Windows.Forms.Application]::DoEvents()
    $startButton.PerformClick()
    if (-not $script:botProcess) { throw 'Start button failed' }
    Start-Sleep -Milliseconds 700
    Read-Output
    if ($humanBox.Text -notmatch 'Спам-сообщение удалено') { throw 'Log streaming failed' }
    $stopButton.PerformClick()
    if (-not $script:botProcess.WaitForExit(5000)) { throw 'Stop button failed' }
    $startButton.Enabled = $true
    $startButton.PerformClick()
    if ($script:botProcess.HasExited) { throw 'Restart failed' }
    $taskTestProcess = $script:botProcess
    $form.Close()
    if (-not $taskTestProcess.HasExited) { throw 'Close must stop process' }
    Remove-Item -LiteralPath $script:configPath
    Write-Output 'GUI smoke test OK: render, start, log streaming, stop, restart, close'
    exit
}
$mutex = [Threading.Mutex]::new($false, 'Local\TelegramAntispamBotWindow')
if (-not $mutex.WaitOne(0)) {
    [Windows.Forms.MessageBox]::Show('Окно управления уже открыто. Найдите его на панели задач.', 'Антиспам') | Out-Null
    $mutex.Dispose()
    exit
}
try { $timer.Start(); [Windows.Forms.Application]::Run($form) }
finally { $mutex.ReleaseMutex(); $mutex.Dispose(); $timer.Dispose(); $form.Dispose() }
