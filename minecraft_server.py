import os
from dataclasses import dataclass

@dataclass
class MinecraftServer:
    server_address: str = os.getenv("SERVER_ADDRESS")  # или IP
    query_port: int = 25565
    check_interval: int = 60  # секунд между проверками
    wd_poweroff_cooldown: int = 10 * 60  # 10 минут
    version: str = ""
    version_number: str = ""
    # runtime state
    online: bool = False
    players_online: int | None  = None
    last_check: float | None = None # Пока не используется
    shutdown_remaining: int | None = None # Осталось до перезапуска

    def reset_runtime(self):
        self.online = False
        self.players_online = None
        self.shutdown_remaining = None
        self.last_check = None

mc_server = MinecraftServer() # Общий shared instance Minecraft сервера