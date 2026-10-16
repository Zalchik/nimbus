"""English interface texts. Keys are the Russian source texts exactly as they appear in tr(…)
calls; placeholders in {braces} must stay the same. A text missing here shows in Russian
(tests/test_core_logic.py checks that none is missing)."""

TEXTS = {
    # -- connection, core, controller -------------------------------------------------------
    "в фоне": "in the background",
    "Запущена": "Running",
    "Стабильный": "Stable",
    "Самый быстрый": "Fastest",
    "код {returncode}": "code {returncode}",
    "код {code}": "code {code}",
    "TUN не работает, пока включены «Мобильный хот-спот» или общий доступ к интернету (ICS): Windows "
    "заворачивает соединения ядра обратно в туннель. Выключите хот-спот или в его настройках раздавайте "
    "подключение Nimbus.":
        "TUN doesn't work while Mobile hotspot or Internet Connection Sharing (ICS) is on: Windows loops "
        "the core's connections back into the tunnel. Turn the hotspot off, or share the Nimbus "
        "connection in its settings.",
    "{name} не отвечает": "{name} doesn't respond",
    "на {ms} мс быстрее, чем {name}": "{ms} ms faster than {name}",
    "Балансировщик": "Balancer",
    "Загрузка подписки…": "Loading the subscription…",
    "Обновление подписок…": "Updating subscriptions…",
    "Проверка задержки…": "Checking latency…",
    "Загрузка geoip/geosite…": "Downloading geoip/geosite…",
    "В балансировщике «{name}» нет серверов: добавьте их через правый клик → «Изменить…».":
        "The balancer “{name}” has no servers: add some with right click → “Edit…”.",
    "Не удалось подключиться: {text}": "Couldn't connect: {text}",
    "Ядро остановилось ({last}). Переподключение…": "The core stopped ({last}). Reconnecting…",
    "Добавлено: {title} — {n} {servers}": "Added: {title} — {n} {servers}",
    "Не удалось загрузить подписку: {err}": "Couldn't load the subscription: {err}",
    "Пинг: {err}": "Ping: {err}",
    "Geo-файлы обновлены. Применятся при следующем подключении.":
        "Geo files updated. They take effect on the next connection.",
    "Не удалось обновить geo-файлы: {err}": "Couldn't update the geo files: {err}",
    "Сначала добавьте подписку или сервер.": "Add a subscription or a server first.",
    "Не найдено ядро: {exe}": "Core not found: {exe}",
    "Сеть сменилась ({bound} → {new}), переподключение…": "The network changed ({bound} → {new}), reconnecting…",
    "Ядро упало несколько раз подряд. Kill switch держит интернет заблокированным — нажмите «Подключиться» "
    "или выйдите из программы.":
        "The core crashed several times in a row. The kill switch keeps the internet blocked: click "
        "“Connect” or quit the app.",
    "Ядро упало несколько раз подряд: {last}": "The core crashed several times in a row: {last}",
    "[nimbus] не удалось закрепить узел {target}: {err}": "[nimbus] couldn't pin node {target}: {err}",
    "Не удалось распознать: ": "Couldn't recognize: ",
    "Новая группа": "New group",
    "нет активного подключения к интернету": "no active internet connection",
    "Автозапуск: {e}": "Start with the system: {e}",
    "Не обновились: ": "Not updated: ",
    "Подписки обновлены": "Subscriptions updated",
    "{name}: подозрительно маленький файл": "{name}: suspiciously small file",
    "Не удалось запустить обновление: {e}": "Couldn't start the update: {e}",
    "Адрес {ip} уже занят другим TUN-адаптером: закройте другой VPN-клиент (Throne, sing-box, v2rayN…) и "
    "подключитесь снова":
        "Address {ip} is already taken by another TUN adapter: close the other VPN client (Throne, "
        "sing-box, v2rayN…) and connect again",
    "Xray не открыл порт для TUN за 5 секунд": "Xray didn't open the TUN port within 5 seconds",
    "{name} завершился сразу после запуска": "{name} exited right after starting",
    "Порт {port} занят другой программой (другой VPN-клиент?)":
        "Port {port} is taken by another program (another VPN client?)",
    "TUN-адаптер не поднялся за 25 секунд": "The TUN adapter didn't come up within 25 seconds",

    # -- tray, app ------------------------------------------------------------------------------
    "Подключиться": "Connect",
    "Открыть": "Open",
    "Выход": "Quit",
    "Системный прокси": "System proxy",
    "Сервер не выбран": "No server selected",
    "Недавние": "Recent",
    "Балансировщики": "Balancers",
    "Весь трафик": "All traffic",
    "Весь трафик, включая российские сайты, идёт через VPN":
        "All traffic, Russian sites included, goes through the VPN",
    "Отключиться": "Disconnect",
    "Доступна новая версия {version}. Откройте Nimbus, чтобы обновиться.":
        "Version {version} is available. Open Nimbus to update.",
    "Нужны права администратора": "Administrator rights needed",
    "Режим TUN создаёт виртуальный сетевой адаптер и меняет маршруты — для этого Windows требует права "
    "администратора. Перезапустить Nimbus от имени администратора?":
        "TUN mode creates a virtual network adapter and changes routes, which Windows allows only to "
        "administrators. Restart Nimbus as administrator?",
    "Перезапустить": "Restart",
    "Запуск от имени администратора отменён.": "Running as administrator was cancelled.",
    "Все балансировщики ({n})…": "All balancers ({n})…",
    "Умная": "Smart",
    "Правила маршрутизации от вашего VPN-провайдера": "Routing rules from your VPN provider",
    "Пресет: {name}": "Preset: {name}",
    "Пресеты": "Presets",
    "Настроить пресеты…": "Set up presets…",
    "подключено": "connected",
    "отключено": "disconnected",
    "Nimbus обновлён до версии {version}": "Nimbus is updated to version {version}",
    "Подключено: ": "Connected: ",
    "Выбран: ": "Selected: ",
    "Обновление не установилось: файлы программы были заняты. Прежняя версия на месте, попробуйте ещё раз":
        "The update wasn't installed: the program files were in use. The previous version is still "
        "there, try again",

    # -- dialogs ----------------------------------------------------------------------------------
    "Да": "Yes",
    "Отмена": "Cancel",
    "Понятно": "OK",
    "Готово": "Done",
    "Сохранить": "Save",
    "нет ответа": "no response",
    "{latency} мс": "{latency} ms",
    "Свой…": "Custom…",
    "User-Agent подписки": "Subscription User-Agent",
    "От него зависит формат подписки: с Happ или v2rayN панели (Remnawave, Marzban) отдают полные "
    "Xray-конфиги с балансировщиком. После сохранения подписка обновится.":
        "It decides the subscription format: with Happ or v2rayN, panels (Remnawave, Marzban) send full "
        "Xray configs with a balancer. The subscription is updated after saving.",
    "Как в настройках  ·  {default}": "As in settings  ·  {default}",
    "Логи Xray": "Xray logs",
    "Логи ядра": "Core logs",
    "Подробность задаётся в настройках → Дополнительно → Уровень логов. Соединения видны на уровне info и "
    "debug.":
        "The detail is set in Settings → Advanced → Log level. Connections show up at the info and debug "
        "levels.",
    "Закрыть": "Close",
    "Подписка": "Subscription",
    "Добавить подписку": "Add a subscription",
    "Ссылка на подписку от VPN-провайдера (https://…). Серверы, трафик и срок подписки подтянутся сами и "
    "будут обновляться автоматически.":
        "The subscription link from your VPN provider (https://…). Servers, traffic and the expiry date "
        "are loaded and kept up to date automatically.",
    "Добавить": "Add",
    'vless://…\nhy2://…\n\nили {"outbounds": [...]}': 'vless://…\nhy2://…\n\nor {"outbounds": [...]}',
    "Загрузить файл…": "Load a file…",
    "Файлы с конфигами": "Config files",
    "Конфиги (*.json *.txt *.conf);;Все файлы (*)": "Configs (*.json *.txt *.conf);;All files (*)",
    "Отметьте серверы из любых подписок и групп. Nimbus сам проверяет их скорость и ведёт трафик через "
    "самый быстрый, а если тот перестанет отвечать, переключается на следующий без переподключения. "
    "Подписка или группа, отмеченная целиком, берётся вместе с будущими серверами. Несколько подряд "
    "отмечаются протягиванием мыши с зажатой кнопкой.":
        "Tick servers from any subscriptions and groups. Nimbus checks their speed and sends traffic "
        "through the fastest one; if it stops responding, it moves to the next one without reconnecting. "
        "A subscription or group ticked as a whole brings its future servers too. Drag with the mouse "
        "button held to tick several in a row.",
    "Проверить задержку всех серверов в списке": "Check the latency of every server in the list",
    "Режим": "Mode",
    "Проверять скорость каждые": "Check speed every",
    " с": " s",
    "Свернуть все": "Collapse all",
    "Развернуть все": "Expand all",
    "Держится за сервер, пока он отвечает. Переходит на другой, только если тот быстрее хотя бы на {ms} мс "
    "и на {pct}%: IP меняется редко, сайты не разлогинивают.":
        "Stays on a server while it responds and moves only to one at least {ms} ms and {pct}% faster: "
        "the IP rarely changes and sites don't log you out.",
    "Всегда самый быстрый сервер. IP может меняться чаще: банки и игры иногда просят войти заново.":
        "Always the fastest server. The IP may change more often: banks and games sometimes ask you to "
        "sign in again.",
    "Например, Hiddify/2.5.7": "For example, Hiddify/2.5.7",
    "Копировать": "Copy",
    "Очистить": "Clear",
    "Папка с данными": "Data folder",
    "Группа — ваша папка для конфигов. Дайте ей название и, если хотите, сразу добавьте конфиги: текстом "
    "или файлом. Позже — кнопкой «+» справа от названия группы или правым кликом по ней.":
        "A group is your folder for configs. Give it a name and, if you like, add configs right away as "
        "text or files. Later: the “+” button next to the group name, or right click on the group.",
    "Конфиги": "Configs",
    "Добавить конфиги": "Add configs",
    "Ссылки vless://, vmess://, trojan://, ss://, hy2://, socks://, wireguard:// — по одной на строку — или "
    "Xray JSON. Можно загрузить файлы .json / .txt или перетащить их в это окно.":
        "vless://, vmess://, trojan://, ss://, hy2://, socks://, wireguard:// links, one per line, or "
        "Xray JSON. You can load .json / .txt files or drop them onto this window.",
    "Группа": "Group",
    "Создать группу": "Create group",
    "Файлы: {names}": "Files: {names}",
    "проверка…": "checking…",
    "проверить": "check",
    "Изменить балансировщик": "Edit balancer",
    "Новый балансировщик": "New balancer",
    "Название, например «Европа»": "Name, for example “Europe”",
    "Поиск по серверам": "Search servers",
    "Проверить все": "Check all",
    "Свернуть или развернуть": "Collapse or expand",
    "Проверить задержку серверов «{title}»": "Check the latency of “{title}” servers",
    "Создать": "Create",
    "Выбрано: {n} {servers}": "Selected: {n} {servers}",
    "Серверы не выбраны": "No servers selected",
    "Название группы, например «Работа»": "Group name, for example “Work”",
    "найдено конфигов: {n}": "configs found: {n}",
    "конфиги не распознаны": "no configs recognized",
    "Проверить задержку": "Check latency",
    "Отметить все": "Tick all",
    "Снять все": "Untick all",
    "файл больше 5 МБ": "the file is larger than 5 MB",
    "Свернуть": "Collapse",
    "Развернуть": "Expand",
    "Проверить отмеченные ({n})": "Check ticked ({n})",

    # -- main window -------------------------------------------------------------------------------
    "Это зашифрованная ссылка Happ (happ://crypt…): защищённый формат Happ, Nimbus такие ссылки не "
    "расшифровывает. Попросите у VPN-провайдера обычную ссылку на подписку — она начинается с https://. Её "
    "можно вставить в Nimbus кнопкой «Добавить» или клавишами Ctrl+V.":
        "This is an encrypted Happ link (happ://crypt…), a protected Happ format that Nimbus doesn't "
        "decrypt. Ask your VPN provider for the plain subscription link: it starts with https://. Paste "
        "it into Nimbus with the “Add” button or Ctrl+V.",
    "Не подключено": "Not connected",
    "Подключение": "Connecting",
    "Подключено": "Connected",
    "Отключение": "Disconnecting",
    "Умная* — маршруты из вашей подписки: какие сайты открываются без VPN, решает VPN-провайдер":
        "Smart* — routes from your subscription: your VPN provider decides which sites open without the VPN",
    "* Правила маршрутизации задаёт ваш VPN-провайдер в подписке: {what}, остальные — через VPN.":
        "* Routing rules come from your VPN provider's subscription: {what}, the rest go through the VPN.",
    "Порядок": "Order",
    "Как в подписке у провайдера": "As in the provider's subscription",
    "Пинг": "Ping",
    "Внутри каждой подписки — сначала самые быстрые": "Within each subscription, the fastest first",
    "А–Я": "A–Z",
    "Внутри каждой подписки — по алфавиту, без учёта эмодзи": "Within each subscription, alphabetically, emoji ignored",
    "Весь трафик идёт через VPN: в этом конфиге VPN-провайдер не задал правил маршрутизации, поэтому "
    "выбирать нечего.":
        "All traffic goes through the VPN: the VPN provider set no routing rules in this config, so there's "
        "nothing to choose.",
    "Все сайты, включая российские, идут через VPN. Правила из подписки не используются.":
        "All sites, Russian ones included, go through the VPN. The subscription's rules aren't used.",
    "российские сайты открываются без VPN": "Russian sites open without the VPN",
    "часть сайтов открывается без VPN": "some sites open without the VPN",
    "Авто · {n} {nodes}": "Auto · {n} {nodes}",
    "Серверы ({n})": "Servers ({n})",
    "Пресет «{name}»: через VPN идут только {what}, всё остальное — напрямую.":
        "Preset “{name}”: only {what} go through the VPN, everything else goes direct.",
    "Пресет «{name}»: {what} — без VPN, остальное через VPN.":
        "Preset “{name}”: {what} bypass the VPN, the rest goes through it.",
    " Программы без поддержки системного прокси учитываются только в режиме TUN.":
        " Programs that ignore the system proxy are covered only in TUN mode.",
    "Весь трафик идёт через VPN: в балансировщике серверы разных подписок, поэтому правила провайдера не "
    "применяются.":
        "All traffic goes through the VPN: the balancer has servers from different subscriptions, so "
        "provider rules don't apply.",
    "Весь трафик идёт через VPN: в этом конфиге VPN-провайдер не задал правил маршрутизации. Свои правила — "
    "в пресетах.":
        "All traffic goes through the VPN: the VPN provider set no routing rules in this config. Your own "
        "rules are in presets.",
    "\nСейчас самый быстрый: {node}": "\nFastest right now: {node}",
    "Проверить IP ещё раз": "Check the IP again",
    "IP не определён": "IP unknown",
    "Определяем IP…": "Finding the IP…",
    "Ваш IP через VPN — нажмите, чтобы скопировать": "Your IP through the VPN — click to copy",
    "Не удалось проверить IP заново — показан последний известный":
        "Couldn't check the IP again — showing the last known one",
    "Весь трафик через VPN": "All traffic through the VPN",
    "Пресеты маршрутизации": "Routing presets",
    "Обновить подписки  (F5)": "Update subscriptions  (F5)",
    "Проверить задержку всех серверов  (Ctrl+P)": "Check the latency of all servers  (Ctrl+P)",
    "Настройки": "Settings",
    "Вставить из буфера  (Ctrl+V)": "Paste from the clipboard  (Ctrl+V)",
    "Подписка, ссылки vless:// и т.п. или Xray JSON": "A subscription, vless:// and other links, or Xray JSON",
    "Клик — добавить или убрать, Shift+клик — диапазон, Ctrl+A — все":
        "Click to add or remove, Shift+click for a range, Ctrl+A for all",
    "Добавить выбранные серверы в балансировщик": "Add the selected servers to a balancer",
    "Поделиться выбранными": "Share the selected ones",
    "Удалить выбранные  (Delete)": "Delete the selected ones  (Delete)",
    "Снять выделение  (Esc)": "Clear the selection  (Esc)",
    "IP {ip} скопирован": "IP {ip} copied",
    "Ничего не найдено": "Nothing found",
    "Серверов пока нет": "No servers yet",
    "Попробуйте другой запрос": "Try another search",
    "Нажмите «Добавить» или скопируйте ссылку на подписку и нажмите Ctrl+V":
        "Click “Add”, or copy a subscription link and press Ctrl+V",
    "{used} из {total}": "{used} of {total}",
    "Сортировка": "Sorting",
    "Экспортировать": "Export",
    "Выбрано: {n}": "Selected: {n}",
    "Проверить задержку ({n})": "Check latency ({n})",
    "Удалить ({n})…": "Delete ({n})…",
    "Снять выделение": "Clear the selection",
    "QR-код": "QR code",
    "Ссылки": "Links",
    "Конфигурация": "Configuration",
    "В буфер обмена": "To the clipboard",
    "В файл…": "To a file…",
    ", пропущено: {skipped} (только как конфигурация)": ", skipped: {skipped} (configuration only)",
    " Серверы из подписок ({from_subs}) останутся: при обновлении они вернулись бы, их удаляют вместе с "
    "подпиской.":
        " Subscription servers ({from_subs}) stay: an update would bring them back; they go together with "
        "their subscription.",
    "Удалить": "Delete",
    "В ссылке основной узел из {n}: ссылка не умеет балансировщик. Весь конфиг с автовыбором — через "
    "«Конфигурация».":
        "The link has the main node of {n}: links can't hold a balancer. The whole config with automatic "
        "choice is under “Configuration”.",
    ", пропущено: {skipped}": ", skipped: {skipped}",
    "Переименовать": "Rename",
    "Название группы.": "Group name.",
    "Группа «{name}» и её конфиги ({n}) будут удалены.": "The group “{name}” and its configs ({n}) will be deleted.",
    "Группа «{name}» будет удалена.": "The group “{name}” will be deleted.",
    "Удалить группу": "Delete group",
    "Название подписки. Пусто — как у провайдера.": "Subscription name. Empty: as the provider names it.",
    "Удалить подписку": "Delete subscription",
    "«{title}» и все её серверы будут удалены.": "“{title}” and all its servers will be deleted.",
    "Подписку…": "Subscription…",
    "Конфиги…": "Configs…",
    "Группу…": "Group…",
    "Балансировщик…": "Balancer…",
    "Балансировщик «{name}» создан. Двойной клик — подключиться":
        "Balancer “{name}” created. Double click to connect",
    "Выделить  (Ctrl+клик)": "Select  (Ctrl+click)",
    "Изменить…": "Edit…",
    "Переименовать…": "Rename…",
    "Новый балансировщик…": "New balancer…",
    "Добавлено в «{name}»: {n} {servers}": "Added to “{name}”: {n} {servers}",
    "Название балансировщика.": "Balancer name.",
    " Правила провайдера* тоже действуют.": " The provider's rules* apply too.",
    " Свои правила — в пресетах.": " Your own rules are in presets.",
    "Загрузка": "Download",
    "Отдача": "Upload",
    "Маршрутизация": "Routing",
    "В балансировщик": "To a balancer",
    "Поделиться": "Share",
    "Ваши пресеты маршрутизации": "Your routing presets",
    "Серверы": "Servers",
    "Авто · {n} {servers}": "Auto · {n} {servers}",
    "Нет серверов": "No servers",
    "  ·  самый быстрый": "  ·  fastest",
    "  ·  сейчас {node}": "  ·  now {node}",
    "истекла {when}": "expired {when}",
    "{used}  ·  без лимита": "{used}  ·  unlimited",
    "Файлом…": "As a file…",
    "Поделиться URL подписки": "Share the subscription URL",
    "Каждый конфиг — ссылкой vless://, hy2:// и т.п., по одной в строке":
        "Each config as a vless://, hy2:// or similar link, one per line",
    "Эти конфиги нельзя записать ссылками — поделитесь ими как конфигурацией":
        "These configs can't be written as links: share them as a configuration",
    "Ссылки по одной в строке. Happ, v2rayNG и Hiddify добавят их все; если клиент взял только одну — "
    "поделитесь через буфер обмена.":
        "Links one per line. Happ, v2rayNG and Hiddify add them all; if a client took only one, share "
        "through the clipboard.",
    "Серверы подписки удаляются только вместе с подпиской: при обновлении они вернутся":
        "Subscription servers are deleted only together with the subscription: an update would bring them back",
    "серверы: {n}": "servers: {n}",
    "балансировщики: {n}": "balancers: {n}",
    "Будут удалены выбранные ": "These will be deleted: ",
    "Удалить выбранное": "Delete selected",
    "Удалить серверы": "Delete servers",
    "Этот конфиг нельзя записать ссылкой — поделитесь им как конфигурацией":
        "This config can't be written as a link: share it as a configuration",
    "Отсканируйте в Happ, v2rayNG, Hiddify, Streisand или другом клиенте, чтобы добавить этот сервер.":
        "Scan it in Happ, v2rayNG, Hiddify, Streisand or another client to add this server.",
    "Нечего экспортировать": "Nothing to export",
    "Скопировано ссылок: {n}{tail}": "Links copied: {n}{tail}",
    "Экспорт конфигов": "Export configs",
    "Защищённая ссылка Happ": "Protected Happ link",
    "Группа «{name}» создана, конфигов: {n}": "Group “{name}” created, configs: {n}",
    "Группа «{name}» создана. Добавьте в неё конфиги: «+» справа от названия группы или правый клик по ней.":
        "Group “{name}” created. Add configs to it: “+” next to the group name, or right click on it.",
    "Буфер обмена пуст": "The clipboard is empty",
    "Балансировщик «{name}» сохранён": "Balancer “{name}” saved",
    "Балансировщик {n}": "Balancer {n}",
    "Удалить балансировщик": "Delete balancer",
    "Балансировщик «{name}» будет удалён.": "The balancer “{name}” will be deleted.",
    "Удалить балансировщики": "Delete balancers",
    "Будут удалены балансировщики: {n}.": "Balancers to delete: {n}.",
    " Серверы в подписках и группах останутся на своих местах.":
        " Servers in subscriptions and groups stay where they are.",
    "Браузеры и программы, которые используют системный прокси. Без прав администратора":
        "Browsers and programs that use the system proxy. No administrator rights needed",
    "Весь трафик компьютера, включая игры. Нужны права администратора":
        "All of the computer's traffic, games included. Needs administrator rights",
    "Умная*": "Smart*",
    "Поднимаем TUN-адаптер…": "Bringing up the TUN adapter…",
    "Запускаем ядро…": "Starting the core…",
    "Возвращаем настройки сети…": "Restoring network settings…",
    "Нажмите, чтобы подключиться": "Click to connect",
    " — нажмите, чтобы выбрать": " — click to choose",
    "Мои серверы": "My servers",
    "{hours} ч  ·  до {when}": "{hours} h  ·  until {when}",
    "{days} дн.  ·  до {when}": "{days} d  ·  until {when}",
    "Сайт": "Website",
    "Поддержка": "Support",
    "Как у всех ({common})": "Same as all ({common})",
    "Поделиться ({k})": "Share ({k})",
    "Добавить в балансировщик ({k})": "Add to a balancer ({k})",
    "Конфигурации скопированы: {n} (Xray JSON, массивом)": "Configurations copied: {n} (Xray JSON array)",
    "Сохранить конфигурации": "Save configurations",
    "Ссылок в коде: {n}{tail}.": "Links in the code: {n}{tail}.",
    "Сохранить ссылки": "Save links",
    "Слишком длинно для QR-кода — поделитесь через буфер обмена":
        "Too long for a QR code: share through the clipboard",
    "Конфигурация (Xray JSON) скопирована": "Configuration (Xray JSON) copied",
    "Сохранить конфигурацию": "Save configuration",
    "Ссылка скопирована": "Link copied",
    "Сохранено ссылок: {n}{tail}": "Links saved: {n}{tail}",
    "Добавлено серверов: {n}": "Servers added: {n}",
    "Добавлено конфигов: {n} → «{title}»": "Configs added: {n} → “{title}”",
    "Язык интерфейса": "Interface language",
    "Новый язык заработает после перезапуска Nimbus. Перезапустить сейчас? Подключение восстановится само.":
        "The new language takes effect after Nimbus restarts. Restart now? The connection comes back by itself.",
    "Позже": "Later",
    ". У отдельной группы — правый клик по ней → «Сортировка»": ". For a single group: right click on it → “Sorting”",
    "прокси": "proxy",
    "Группа пуста. Добавьте в неё конфиги текстом или файлом: кнопкой «+» справа от названия группы, правым "
    "кликом по группе или кнопкой ниже.":
        "The group is empty. Add configs as text or files: the “+” button next to the group name, a right "
        "click on the group, or the button below.",
    "Создать балансировщик…": "Create a balancer…",
    "Удалить все балансировщики": "Delete all balancers",
    "URL подписки скопирован": "Subscription URL copied",
    "Отсканируйте в Happ, v2rayNG, Hiddify или другом клиенте — подписка добавится вместе с обновлениями.":
        "Scan it in Happ, v2rayNG, Hiddify or another client: the subscription is added with its updates.",
    "Сохранено конфигураций: {n}": "Configurations saved: {n}",
    "Конфигурация сохранена": "Configuration saved",
    "В ссылке нет адреса подписки или конфигов": "The link has no subscription address or configs",
    "Добавить в балансировщик": "Add to a balancer",
    "Переместить в группу": "Move to group",
    "Обновить": "Update",
    "Отправлять HWID": "Send HWID",
    "Включается само, если без HWID подписка не загрузилась. Режим для всех подписок — в настройках, "
    "вкладка «Подписки»":
        "Turns on by itself if the subscription didn't load without an HWID. The mode for all "
        "subscriptions is in Settings, the “Subscriptions” tab",
    "Добавить конфиги…": "Add configs…",

    # -- presets ------------------------------------------------------------------------------------
    "Программы различаются в любом режиме, но в режиме «Системный прокси» через Nimbus проходят только те, "
    "что используют системный прокси: браузеры, Telegram, Discord и т.п. Для игр включите TUN.":
        "Programs are told apart in either mode, but in “System proxy” mode only those that use the "
        "system proxy go through Nimbus: browsers, Telegram, Discord and so on. Turn on TUN for games.",
    "Отмеченные программы и сайты работают напрямую, без VPN. Всё остальное идёт через VPN.":
        "Ticked programs and sites go direct, without the VPN. Everything else goes through the VPN.",
    "Через VPN идут только отмеченные программы и сайты. Всё остальное работает напрямую.":
        "Only ticked programs and sites go through the VPN. Everything else goes direct.",
    "пусто": "empty",
    "выбрано: {n}": "selected: {n}",
    "Пресет маршрутизации": "Routing preset",
    "Вместе с правилами провайдера (Умная*)": "Together with the provider's rules (Smart*)",
    "Если в конфиге есть правила маршрутизации от VPN-провайдера, они продолжают работать вместе с "
    "пресетом: например, российские сайты тоже открываются без VPN.":
        "If the config has routing rules from the VPN provider, they keep working together with the "
        "preset: for example, Russian sites also open without the VPN.",
    "Искать заново": "Search again",
    "По одному в строке. Домен включает все поддомены. Можно IP и подсети, а также готовые списки "
    "geosite:… и geoip:… (например, geosite:youtube, geoip:ru).":
        "One per line. A domain covers all its subdomains. IPs and subnets work too, and the ready lists "
        "geosite:… and geoip:… (for example, geosite:youtube, geoip:ru).",
    "Запущено {programs}, с окном — {windows}. Нет нужной — запустите её и нажмите «Обновить».":
        "Running: {programs}, {windows} with a window. Missing one? Start it and click “Update”.",
    "Ищем установленные программы…": "Looking for installed programs…",
    "Найдено {programs} за {took} с. Нет нужной — добавьте файл или папку.":
        "Found {programs} in {took} s. Missing one? Add its file or folder.",
    "Выберите программу": "Choose a program",
    "Программы (*.exe);;Все файлы (*)": "Programs (*.exe);;All files (*)",
    "Папка программы или игры — учитываются все её .exe": "A program or game folder: all its .exe files count",
    "Мой пресет": "My preset",
    "Свои правила: какие программы и сайты идут мимо VPN или, наоборот, только через него. Созданный пресет "
    "появляется на главном экране в «Маршрутизации» рядом с «Умная*» и «Весь трафик».":
        "Your own rules: which programs and sites bypass the VPN or, the other way round, only use it. A "
        "preset you create shows up on the main screen under “Routing”, next to “Smart*” and “All traffic”.",
    "Создать пресет…": "Create a preset…",
    "Пресетов пока нет.": "No presets yet.",
    "Удалить пресет": "Delete preset",
    "Пресет «{name}» будет удалён.": "The preset “{name}” will be deleted.",
    " и ": " and ",
    "Новый пресет": "New preset",
    "Название, например «Игры без VPN»": "Name, for example “Games without VPN”",
    "Программы": "Programs",
    "Поиск программы": "Search programs",
    "Добавить файл…": "Add a file…",
    "Добавить папку…": "Add a folder…",
    "Сайты и IP": "Sites and IPs",
    "Например:": "For example:",
    "+ Российские сайты": "+ Russian sites",
    "+ Локальная сеть": "+ Local network",
    "   ·   папка": "   ·   folder",
    "Не понял строку сайтов: «{line}». Она будет пропущена.": "Couldn't read the site line “{line}”. It will be skipped.",
    "Отметьте хотя бы одну программу или впишите сайт.": "Tick at least one program or enter a site.",
    "в обход VPN": "bypassing the VPN",
    "только через VPN": "only through the VPN",
    "В обход VPN": "Bypass VPN",
    "Только через VPN": "Only through VPN",
    "Все": "All",
    "Установленные программы и игры": "Installed programs and games",
    "Запущенные": "Running",
    "Программы, которые работают сейчас; с окном — сверху": "Programs running now; those with a window first",

    # -- server list ----------------------------------------------------------------------------------
    "Проверить задержку серверов группы": "Check the latency of the group's servers",
    "Обновить подписку": "Update the subscription",
    "· НЕ ОБНОВИЛАСЬ": "· NOT UPDATED",
    "Осталось": "Left",
    "Трафик": "Traffic",
    "подключено  ·  ": "connected  ·  ",
    "мс": "ms",
    "Создать балансировщик": "Create a balancer",
    "Добавить конфиги в эту группу — текстом или файлом": "Add configs to this group as text or files",
    "Не удалось обновить: {error}": "Couldn't update: {error}",

    # -- settings -------------------------------------------------------------------------------------
    "tab|Подключение": "Connection",
    "Маршруты": "Routes",
    "Дополнительно": "Advanced",
    "Подписки": "Subscriptions",
    "Приложение": "App",
    "Проверить обновления": "Check for updates",
    "Проверяем…": "Checking…",
    "Новый": "New",
    "Сгенерировать случайный HWID": "Generate a random HWID",
    "Сбросить": "Reset",
    "Вернуть HWID этого компьютера": "Back to this computer's HWID",
    "Открыть папку с данными": "Open the data folder",
    "Удалить Nimbus…": "Uninstall Nimbus…",
    "Запустить деинсталлятор. Он спросит подтверждение, закроет Nimbus и предложит оставить или удалить "
    "настройки и подписки":
        "Run the uninstaller. It asks to confirm, closes Nimbus and offers to keep or delete settings and "
        "subscriptions",
    "Не удалось проверить: {error}": "Couldn't check: {error}",
    "  (этого компьютера)": "  (this computer's)",
    "Доступна версия {version}": "Version {version} is available",
    "Установлена последняя версия ({version})": "You have the latest version ({version})",
    "SOCKS-порт": "SOCKS port",
    "HTTP-порт": "HTTP port",
    "Без правил провайдера": "Without provider rules",
    "Удалённый DNS": "Remote DNS",
    "Прямой DNS": "Direct DNS",
    "Mux-потоков": "Mux streams",
    "Пакеты": "Packets",
    "Длина": "Length",
    "Интервал, мс": "Interval, ms",
    "Уровень логов": "Log level",
    "Имя устройства": "Device name",
    "Интервал, ч": "Interval, h",
    "URL для пинга": "Ping URL",
    "Таймаут пинга, с": "Ping timeout, s",
    "Язык": "Language",
    "TUN: strict route — блокирует DNS мимо туннеля и IPv6, если туннель его не несёт (Windows Filtering "
    "Platform). Прокси: при падении ядра прокси остаётся включённым, и трафик не уходит напрямую.":
        "TUN: strict route blocks DNS outside the tunnel, and IPv6 if the tunnel doesn't carry it (Windows "
        "Filtering Platform). Proxy: if the core crashes, the proxy stays on and traffic doesn't go direct.",
    "Прокси для консольных программ (HTTP_PROXY / HTTPS_PROXY)": "Proxy for console programs (HTTP_PROXY / HTTPS_PROXY)",
    "Режим прокси: Claude Code, git, curl, npm и другие программы, которые не видят системный прокси Windows, "
    "тоже пойдут через VPN. Действует на программы, запущенные после подключения; при отключении переменные "
    "убираются.":
        "Proxy mode: Claude Code, git, curl, npm and other programs that ignore the system proxy go through "
        "the VPN too. Applies to programs started after connecting; the variables are removed on disconnect.",
    "Разрешить подключения из локальной сети": "Allow connections from the local network",
    "Умная* — правила маршрутизации из подписки": "Smart* — routing rules from the subscription",
    "* Правила задаёт ваш VPN-провайдер в конфиге: например, российские сайты открываются без VPN, поэтому "
    "пинг до них такой же, как без VPN. Nimbus их только применяет. Выключено (режим «Весь трафик»): вместо "
    "них работают правила ниже. Балансировщик провайдера сохраняется в любом случае.":
        "* Your VPN provider sets the rules in the config: for example, Russian sites open without the VPN, "
        "so their ping is the same as without it. Nimbus only applies them. Off (“All traffic” mode): the "
        "rules below work instead. The provider's balancer is kept either way.",
    "Блокировать рекламу (geosite:category-ads-all)": "Block ads (geosite:category-ads-all)",
    "Локальные сети напрямую": "Local networks direct",
    "Обновить geoip/geosite (Loyalsoldier)": "Update geoip/geosite (Loyalsoldier)",
    "FakeDNS (только TUN)": "FakeDNS (TUN only)",
    "Удалённый DNS идёт через туннель. Прямой используется для российских доменов в режиме обхода. Форматы: "
    "1.1.1.1, https://1.1.1.1/dns-query, tcp://8.8.8.8, quic+local://dns.adguard.com":
        "Remote DNS goes through the tunnel. Direct DNS is used for Russian domains in bypass mode. "
        "Formats: 1.1.1.1, https://1.1.1.1/dns-query, tcp://8.8.8.8, quic+local://dns.adguard.com",
    "Sniffing (определять домен по трафику; в TUN включён всегда)":
        "Sniffing (find the domain from the traffic; always on in TUN)",
    "Mux (не используется с XTLS Vision)": "Mux (not used with XTLS Vision)",
    "Фрагментация TLS ClientHello": "TLS ClientHello fragmentation",
    "Mux и фрагментация применяются к серверам из ссылок; конфиги провайдера не изменяются.":
        "Mux and fragmentation apply to servers from links; provider configs aren't changed.",
    "Панели (Remnawave, Marzban) выбирают формат подписки по User-Agent. С Happ или v2rayN приходят полные "
    "Xray-конфиги с балансировщиком. Для отдельной подписки его можно сменить правой кнопкой по ней.":
        "Panels (Remnawave, Marzban) choose the subscription format by User-Agent. With Happ or v2rayN they "
        "send full Xray configs with a balancer. For a single subscription, change it with a right click on it.",
    "HWID — идентификатор устройства для панелей с лимитом устройств (Remnawave и др.). Пустое поле — HWID "
    "этого компьютера; свой можно вписать или сгенерировать, например чтобы перенести устройство с другого "
    "клиента. «Автоматически»: для каждой подписки решается отдельно и запоминается; переключить вручную — "
    "правый клик по подписке → «Отправлять HWID».":
        "HWID is a device ID for panels that limit devices (Remnawave and others). Empty: this computer's "
        "HWID; you can enter or generate your own, for example to move a device from another client. "
        "“Automatically”: decided and remembered per subscription; to switch it by hand, right click on the "
        "subscription → “Send HWID”.",
    "Автообновление подписок": "Update subscriptions automatically",
    "Обновлять при запуске": "Update at launch",
    "Запускать вместе с Windows": "Start with Windows",
    "Запускать свёрнутым в трей": "Start minimized to the tray",
    "Подключаться при запуске": "Connect at launch",
    "Закрытие окна сворачивает в трей": "Closing the window minimizes to the tray",
    "Сообщать, когда балансировщик меняет сервер": "Notify when a balancer switches servers",
    "Проверять обновления (при запуске и каждые {n} ч)": "Check for updates (at launch and every {n} h)",
    "{app} {version} · {kind} · ядро Xray-core · шрифт Montserrat · {rights}":
        "{app} {version} · {kind} · Xray-core · Montserrat font · {rights}",
    "TUN — весь трафик (нужен администратор)": "TUN — all traffic (needs administrator)",
    "Российские сайты напрямую": "Russian sites direct",
    "Автоматически — только если без него подписка не загружается":
        "Automatically — only if the subscription doesn't load without it",
    "Всегда": "Always",
    "Никогда": "Never",
    "Как в системе": "As in the system",
    "администратор": "administrator",
    "обычные права": "standard rights",
    "установлен": "installed",
    "без установки": "not installed",

    # -- sharing, theme -------------------------------------------------------------------------------
    "Текст (*.txt)": "Text (*.txt)",
    "{filter};;Все файлы (*)": "{filter};;All files (*)",
    "Сохранить PNG…": "Save PNG…",
    "Копировать текст": "Copy text",
    "Скопировано в буфер обмена": "Copied to the clipboard",
    "Сохранить QR-код": "Save QR code",
    "Сохранено: {name}": "Saved: {name}",
    "Б": "B",
    "КБ": "KB",
    "МБ": "MB",
    "ГБ": "GB",
    "ТБ": "TB",
    "Б/с": "B/s",
    "КБ/с": "KB/s",
    "МБ/с": "MB/s",
    "ГБ/с": "GB/s",
    "Включить светлую тему": "Switch to the light theme",
    "Включить тёмную тему": "Switch to the dark theme",
    "Ошибка": "Error",

    # -- updates --------------------------------------------------------------------------------------
    "Обновление": "Update",
    "Найдено обновление": "Update available",
    "Что нового": "What's new",
    "Не предлагать эту версию. О следующей Nimbus сообщит снова":
        "Don't offer this version. Nimbus will tell you about the next one",
    "Напомнить при следующей проверке": "Remind me at the next check",
    "Скачать": "Download",
    "Загрузка…": "Downloading…",
    "Подключаемся к GitHub…": "Connecting to GitHub…",
    "Установка…": "Installing…",
    "Отключаемся и перезапускаем Nimbus с новой версией…": "Disconnecting and restarting Nimbus with the new version…",
    "Не удалось запустить обновление: {err}": "Couldn't start the update: {err}",
    "Повторить": "Retry",
    "Выпущена {date}": "Released {date}",
    "Открыть страницу релиза: эта копия запущена из исходников":
        "Open the release page: this copy runs from source",
    "Не удалось скачать обновление: {err}": "Couldn't download the update: {err}",
    "Проверяем файл…": "Checking the file…",
    "Проверяем и распаковываем…": "Checking and unpacking…",
    "файл скачался не полностью ({size} из {want_size} байт)":
        "the file didn't download completely ({size} of {want_size} bytes)",
    "контрольная сумма SHA-256 не совпадает: файл повреждён или подменён":
        "the SHA-256 checksum doesn't match: the file is damaged or replaced",
    "в {file} нет {name}": "{file} has no {name}",
    "в релизе {tag} нет файла {name}": "release {tag} has no file {name}",
    "в архиве нет программы": "the archive has no program in it",
    "эта копия не обновляется сама": "this copy doesn't update itself",
    "в архиве недопустимый путь: {member}": "the archive has a forbidden path: {member}",
    "загрузка отменена": "download cancelled",
}

# plural(n, one, few, many) in English: the Russian "one" form -> (singular, plural).
PLURALS = {
    "сервер": ("server", "servers"),
    "узел": ("node", "nodes"),
    "программа": ("program", "programs"),
    "сайт": ("site", "sites"),
}
