import asyncio
import httpx
from nicegui import ui

# Store chat messages
messages = []

def update_chat():
    chat_content = ""
    for sender, text in messages:
        chat_content += f"**{sender}:** {text}\n\n"
    chat_display.content = chat_content

async def send_message():
    user_text = user_input.value.strip()
    if not user_text:
        return
    # Append user message
    messages.append(("User", user_text))
    update_chat()
    user_input.value = ""

    # Call backend API with streaming enabled
    url = "http://localhost:8000/chat"
    headers = {"Content-Type": "application/json"}
    payload = {"message": user_text, "streaming": True}

    async with httpx.AsyncClient(timeout=None) as client:
        try:
            # Initiate POST request with streaming response using stream() context manager
            async with client.stream("POST", url, json=payload, headers=headers, timeout=None) as response:
                response.raise_for_status()

                ai_text = ""
                # Stream response content chunk by chunk
                async for chunk in response.aiter_text():
                    if chunk:
                        ai_text += chunk
                        # Update last AI message dynamically
                        if messages and messages[-1][0] == "AI":
                            messages[-1] = ("AI", ai_text)
                        else:
                            messages.append(("AI", ai_text))
                        update_chat()
                        await asyncio.sleep(0)  # Yield control to event loop for UI responsiveness
        except Exception as e:
            error_msg = f"[Error contacting API: {e}]"
            messages.append(("AI", error_msg))
            update_chat()

ui.label('🧠 AI Chat').classes('text-2xl font-bold mb-4')

chat_display = ui.markdown("").classes('w-full h-80 overflow-auto border rounded p-2 mb-4')

with ui.row():
    user_input = ui.input(placeholder='Type your message here...').props('class=flex-grow')
    ui.button('Send', on_click=lambda: asyncio.create_task(send_message())).props('class=ml-2')

ui.run(title="AI Chat with NiceGUI")