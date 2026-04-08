### Using
1. Install Docker
2. Clone this repository
3. Add values to .env file
4. Configure and run deploy.sh script

Alternatively you can manually build and start Docker container using commands provided below. Parameters in square brackets are optional
##### Building and running Docker image
```shell
sudo docker build -t minecraft-bot .
sudo docker run [-d --name minecraft_bot --memory="128m" --cpus="0.5" --restart unless-stopped] --env-file .env minecraft-bot
```

##### Copying authorization config
```shell
sudo docker cp minecraft_bot:/app/authorized.json .
```
