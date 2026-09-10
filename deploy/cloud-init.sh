#!/bin/bash
# Первоначальная настройка облачного сервера под стек «Мафия ВМК».
# Вставляется в поле Cloud-init при создании сервера в панели Timeweb.
# Выполняется один раз, при первой загрузке, от root.
#
# Делает ровно подготовку машины: пакеты, Docker, файрвол, swap, код.
# Стек НЕ поднимает и сертификат НЕ выпускает -- для первого нужны секреты,
# для второго рабочий DNS, и ни того ни другого на этом этапе ещё нет.
#
# СЕКРЕТОВ ЗДЕСЬ БЫТЬ НЕ ДОЛЖНО. Содержимое cloud-init хранится у провайдера
# и доступно изнутри машины через сервис метаданных любому процессу -- то
# есть JWT_SECRET, BOT_TOKEN и пароль базы, вписанные сюда, утекают ровно
# туда, куда не надо. Их заполняют руками в .env после подключения по SSH.
#
# Лог всей работы: /var/log/cmcmafia-init.log
# Проверить, что скрипт доработал: cat /root/ГОТОВО.txt

set -eux

# Порт SSH. 22 наружу -- это непрерывный перебор паролей ботами с первых минут
# жизни публичного адреса; на нестандартном порту он прекращается полностью.
# Переопределяется при запуске:  SSH_PORT=22 bash cloud-init.sh
SSH_PORT="${SSH_PORT:-2222}"

exec > >(tee -a /var/log/cmcmafia-init.log) 2>&1
echo "=== cmcmafia init $(date -Is) ==="

export DEBIAN_FRONTEND=noninteractive

# На первой загрузке dpkg-блокировку почти наверняка держит штатный
# unattended-upgrades. Без ожидания apt-get падает с "Could not get lock", и
# весь скрипт обрывается на первой же строке.
APT="apt-get -o DPkg::Lock::Timeout=600 -y"

$APT update
$APT install -y ca-certificates curl git ufw

# ---------- Docker из официального репозитория ----------
# Не docker.io из репозитория Ubuntu: там заметно старее и без compose-плагина,
# а docker-compose.yml этого проекта рассчитан на `docker compose`, не на
# отдельный docker-compose.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

$APT update
$APT install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

# ---------- SSH и файрвол ----------
# Наружу нужны только ssh и порты nginx. База, Redis, api и фронтенд портов
# не пробрасывают вовсе и видны лишь внутри docker-сети.
#
# Порядок: сначала переносим sshd и УБЕЖДАЕМСЯ, что он поднялся на новом
# порту, и только потом включаем файрвол. Обратный порядок оставляет окно:
# если sshd не стартует, ufw уже блокирует старый порт, а на новом никого нет.
#
# Drop-in с номером 01: sshd читает их по алфавиту и берёт ПЕРВОЕ найденное
# значение, а в облачных образах лежит 50-cloud-init.conf со своими
# настройками -- файл с большим номером ему проиграл бы.
cat > /etc/ssh/sshd_config.d/01-port.conf <<SSHD
Port $SSH_PORT
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
SSHD
sshd -t
systemctl restart ssh

# Без этой проверки дальше идти нельзя: ufw вот-вот закроет всё, кроме
# $SSH_PORT, и если sshd на нём не слушает -- останется только веб-консоль.
ss -lntp | grep -q ":$SSH_PORT " || {
    echo "sshd не слушает порт $SSH_PORT -- файрвол не трогаю" >&2
    exit 1
}

# 22-й здесь не открывается намеренно: sshd на нём уже не слушает, и правило
# для порта без демона не защищает ни от чего -- только держит дырку открытой.
ufw allow "$SSH_PORT"/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ---------- Swap ----------
# Самая тяжёлая операция на этой машине -- `npm run build` фронтенда, и
# именно она упирается в память. Со swap сборка на 2 ГБ проходит (медленно),
# а на 4 ГБ он просто страхует от случайного OOM в пике.
# swappiness=10: пользоваться им только под реальным давлением, а не гонять
# в него горячие страницы Postgres при свободной памяти.
if [ -z "$(swapon --show --noheadings)" ]; then
    fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
    sysctl -p /etc/sysctl.d/99-swappiness.conf
fi

# ---------- Автоматические обновления безопасности ----------
# После ухода с управляемой платформы патчи ОС -- забота владельца сервера.
# Ставим только security-обновления: они не тянут смену версий пакетов.
$APT install -y unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

# ---------- Код ----------
# Репозиторий публичный, поэтому клонируем прямо здесь, по https и без
# единого секрета. Ключей, deploy key и ssh-агентов не требуется -- а значит
# и утекать через метаданные машины нечему.
if [ ! -d /opt/cmcmafia/.git ]; then
    git clone https://github.com/kobylinskii/cmcmafia.git /opt/cmcmafia
fi
cd /opt/cmcmafia

# Заготовки .env. Существующие не трогаем: скрипт может быть запущен повторно
# на уже настроенной машине, и затирать заполненные секреты он не должен.
for pair in ".env.example:.env" "backend/.env.example:backend/.env" "bot/.env.example:bot/.env"; do
    src="${pair%%:*}"
    dst="${pair##*:}"
    [ -f "$dst" ] || cp "$src" "$dst"
done

# Пароль базы можно сгенерировать прямо тут: он локальный и ни с чем совпадать
# не обязан. JWT_SECRET и BOT_SERVICE_TOKEN -- НЕЛЬЗЯ: при переезде их берут со
# старого хостинга, и подставленное здесь значение выглядело бы заполненным, а
# бот молча перестал бы отвечать (API отдавал бы ему 401).
if [ -z "$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)" ]; then
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" .env
fi

# .env хранят секреты в открытом виде -- читать их должен только root.
chmod 600 .env backend/.env bot/.env

# ---------- Что дальше ----------
{
    cat <<'TXT'
Сервер подготовлен: Docker, файрвол, swap 4 ГБ, автообновления безопасности.
SSH перенесён на порт SSH_PORT_PLACEHOLDER, вход только по ключу.

Код уже в /opt/cmcmafia, файлы .env созданы из примеров,
POSTGRES_PASSWORD сгенерирован.

Дальше руками.

  1. Заполнить переменные окружения:
       cd /opt/cmcmafia && nano .env
         LETSENCRYPT_EMAIL, NEXT_PUBLIC_BOT_USERNAME
       nano backend/.env
         перенести с Railway JWT_SECRET, BOT_SERVICE_TOKEN,
         SUPERADMIN_TELEGRAM_IDS_RAW, BOOTSTRAP_ADMIN_PHONE_RAW
       nano bot/.env
         BOT_TOKEN и тот же BOT_SERVICE_TOKEN, что в backend/.env

     JWT_SECRET и BOT_SERVICE_TOKEN берутся со старого хостинга, а не
     придумываются заново: новый JWT_SECRET разлогинит админов, а разошедшийся
     BOT_SERVICE_TOKEN тихо сломает бота. init-tls.sh это проверит.

  2. Убедиться, что домен уже резолвится в IP этого сервера:
       dig +short cmcmafia.ru

  3. Собрать и выпустить сертификат:
       docker compose build
       ./deploy/init-tls.sh

Полный порядок работ -- TIMEWEB.md в /opt/cmcmafia.
Лог этой подготовки -- /var/log/cmcmafia-init.log
TXT
} > /root/next-steps.txt

# Heredoc'и выше в кавычках -- переменные внутри намеренно не раскрываются
# (в тексте есть $ и обратные кавычки, которые сломались бы). Порт
# подставляем отдельным проходом.
sed -i "s/SSH_PORT_PLACEHOLDER/$SSH_PORT/g" /root/next-steps.txt

# Чтобы инструкция попалась на глаза сразу при входе по ssh, а не лежала
# незамеченным файлом в домашнем каталоге.
echo 'cat /root/next-steps.txt' > /etc/profile.d/cmcmafia-next-steps.sh

echo "=== cmcmafia init готово $(date -Is) ==="
cat /root/next-steps.txt
