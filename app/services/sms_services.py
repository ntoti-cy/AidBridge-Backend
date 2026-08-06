import os
import africastalking

USERNAME = os.getenv("AT_USERNAME")
API_KEY = os.getenv("AT_API_KEY")

africastalking.initialize(USERNAME, API_KEY)

sms = africastalking.SMS


def send_sms(phone_number, message):
    """
    Sends an SMS and returns the Africa's Talking response.
    Raises an exception only if the SDK itself fails.
    """
    response = sms.send(
        message=message,
        recipients=[phone_number],
    )

    return response