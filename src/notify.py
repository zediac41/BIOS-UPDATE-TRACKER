import os, requests

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

def notify(message: str, embeds=None):
  if not WEBHOOK_URL:
    print("[notify] WEBHOOK_URL not set; printing instead:\n", message)
    return
  payload = {"content": message}
  if embeds:
    payload["embeds"] = embeds
  try:
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    resp.raise_for_status()
  except Exception as e:
    print("[notify] failed to send webhook:", e)
