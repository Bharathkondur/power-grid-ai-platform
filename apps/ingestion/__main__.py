from gridpulse.config import Settings
from gridpulse.data.mqtt import run

run(Settings(), "subscribe")
