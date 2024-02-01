# Palworld Notify


## Dependence
```sh
python -V
Python 3.10.12
```

## Config example

Create and edit a file named `.env`.
Not all fields are required.

```.env
ip = "127.0.0.1"
port = 25575
password = "password"

line_notify_token = "0000000000000000000"
discord_webhook_url = "https://discordapp.com/api/webhooks/0000000/000000000000000"

join_message = "palworld - {name} ({steamid}) が参加しました"
leave_message = "palworld - {name} ({steamid}) が退出しました"

wait_time = 5
log_level = "INFO"
```