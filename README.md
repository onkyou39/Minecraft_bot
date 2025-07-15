### Using
1. Install Docker
2. Clone this repository
3. Add values to .env file
```shell
sudo docker build -t minecraft-bot .
sudo docker run [-d --name minecraft_bot --memory="128m" --cpus="0.5"] --env-file .env minecraft-bot
```
