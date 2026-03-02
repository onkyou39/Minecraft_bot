#!/bin/bash
set -e  # Exit on error

CONTAINER_NAME="minecraft-bot"
IMAGE_NAME="minecraft-bot:latest"

echo "📦 Starting deployment of $CONTAINER_NAME..."

echo "💾 Backing up authorized.json from old container..."
docker cp $CONTAINER_NAME:/app/authorized.json . 2>/dev/null || true

echo "🛑 Stopping old container..."
docker stop $CONTAINER_NAME 2>/dev/null || true
docker rm $CONTAINER_NAME 2>/dev/null || true

echo "🗑️ Removing old image..."
docker rmi $IMAGE_NAME 2>/dev/null || true

echo "🏗️ Building new image..."
docker build -t $IMAGE_NAME .

echo "🚀 Starting new container..."
docker run -d --name $CONTAINER_NAME --memory="128m" \
--cpus="0.5" --restart unless-stopped --env-file .env $IMAGE_NAME

echo "✅ Checking container status..."
if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "✅ Successful deploy! Container $CONTAINER_NAME is running."
else
    echo "❌ Something went wrong. Container failed to start."
    echo "📋 Last logs:"
    docker logs $CONTAINER_NAME
    exit 1
fi