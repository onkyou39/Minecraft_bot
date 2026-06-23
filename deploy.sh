#!/bin/bash
set -e  # Exit immediately if any command fails

if [[ $EUID -ne 0 ]]; then
  echo "❗ This script must be run as root"
  exit 1
fi

# ----------------------------
# Config & Argument Parsing
# ----------------------------
CONTAINER_NAME="minecraft-bot"
BOT_ARGS=()  # Array to store arguments passed directly to the Docker container CMD

# Parse command-line arguments
while [ $# -gt 0 ]; do
  case "$1" in
    --debug)
      BOT_ARGS+=("--debug")  # Append flag to the array
      shift 1
      ;;
    *)
      echo "❌ Unknown argument: $1"
      echo "Usage: $0 [--debug]"
      exit 1
      ;;
  esac
done

# Try to get git commit hash for image tagging
# fallback to "latest" if not in git repo
IMAGE_TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "latest")
IMAGE_NAME="$CONTAINER_NAME:$IMAGE_TAG"

echo "📦 Starting deployment of $CONTAINER_NAME..."
echo "🏷️ Image tag: $IMAGE_TAG"
if [ ${#BOT_ARGS[@]} -gt 0 ]; then
  echo "⚙️ Passing arguments to bot: ${BOT_ARGS[*]}"
fi

# ----------------------------
# Detect existing container
# ----------------------------
OLD_CONTAINER_ID=$(docker ps -aq -f name="^/${CONTAINER_NAME}$")

# Backup persistent data BEFORE rebuilding anything
if [ -n "$OLD_CONTAINER_ID" ]; then
  echo "💾 Backing up authorized.json from old container..."
  docker cp "$OLD_CONTAINER_ID":/app/authorized.json . 2>/dev/null || true
fi


# ----------------------------
# Build new image
# ----------------------------
echo "🏗️ Building new image..."
docker build -t "$IMAGE_NAME" .

# Tag image as latest for runtime simplicity
echo "🏷️ Updating latest tag..."
docker tag "$IMAGE_NAME" "$CONTAINER_NAME:latest"


# ----------------------------
# Stop and remove old container
# ----------------------------
OLD_IMAGE_ID=""
if [ -n "$OLD_CONTAINER_ID" ]; then
  OLD_IMAGE_ID=$(docker inspect -f '{{.Image}}' "$OLD_CONTAINER_ID" 2>/dev/null || true)

  echo "🛑 Stopping old container..."
  docker stop "$OLD_CONTAINER_ID" || true

  echo "🗑️ Removing old container..."
  docker rm "$OLD_CONTAINER_ID" || true
fi

# ----------------------------
# Start new container
# ----------------------------
if [ ! -f .env ]; then
    echo "❌ .env file not found in $(pwd)"
    exit 1
fi

echo "🚀 Starting new container..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --memory="128m" \
  --cpus="0.5" \
  --restart unless-stopped \
  --env-file .env \
  "$CONTAINER_NAME:latest" \
  "${BOT_ARGS[@]}"

# ----------------------------
# Health check (basic)
# ----------------------------
echo "✅ Checking container status..."
sleep 3

NEW_IMAGE_ID=""
if [ "$(docker ps -q -f name="^/${CONTAINER_NAME}$")" ]; then
    echo "✅ Successful deploy! Container $CONTAINER_NAME is running."
    echo "🏷️ Running image: $CONTAINER_NAME:$IMAGE_TAG"

    NEW_IMAGE_ID=$(docker inspect -f '{{.Image}}' "$CONTAINER_NAME" 2>/dev/null || true)
    if [ -n "$OLD_IMAGE_ID" ] && [ "$OLD_IMAGE_ID" != "$NEW_IMAGE_ID" ]; then
      echo "🗑️ Removing old image..."
      docker rmi "$OLD_IMAGE_ID" 2>/dev/null || true
    fi

    # Optional cleanup
    # echo "🧹 Cleaning dangling images..."
    # docker image prune -f

else
    echo "❌ Something went wrong. Container failed to start."
    echo "📋 Last logs:"
    docker logs "$CONTAINER_NAME" || true

    echo "🗑️ Cleaning up failed container..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

    # Auto rollback
    if [ -n "$OLD_IMAGE_ID" ]; then
        echo "🔄 Rolling back to previous image ($OLD_IMAGE_ID)..."
        docker run -d \
          --name "$CONTAINER_NAME" \
          --memory="128m" \
          --cpus="0.5" \
          --restart unless-stopped \
          --env-file .env \
          "$OLD_IMAGE_ID" \
          "${BOT_ARGS[@]}"

        # Moving the last tag back to the old stable image.
        docker tag "$OLD_IMAGE_ID" "$CONTAINER_NAME:latest"
        echo "✅ Rollback complete. Old version is running."
    else
        echo "⚠️ No old image found to roll back to."
    fi

    exit 1
fi