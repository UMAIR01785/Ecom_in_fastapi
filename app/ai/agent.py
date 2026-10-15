import json
import logging

from sqlalchemy.orm import Session
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.ai.llm import get_llm
from app.ai.prompts import get_system_message
from app.ai.tools.order_tools import create_order_tools
from app.ai.tools.payment_tools import create_payment_tools
from app.ai.tools.product_tools import create_product_tools
from app.ai.tools.category_tools import create_category_tools
from app.models.chat import ChatMessage

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4
MAX_HISTORY_MESSAGES = 12


def create_admin_tools(db: Session):
    """Create tools using the current database session."""
    return (
        create_order_tools(db)
        + create_payment_tools(db)
        + create_product_tools(db)
        + create_category_tools(db)
    )


def run_admin_agent(
    db: Session,
    history: list[ChatMessage],
) -> str:
    """Generate an admin answer using conversation history and database tools."""

    tools = create_admin_tools(db)
    tools_by_name = {tool.name: tool for tool in tools}

    # Include recent messages, preserving chronological order.
    messages = [get_system_message()]

    for message in history[-MAX_HISTORY_MESSAGES:]:
        if message.role == "user":
            messages.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            messages.append(AIMessage(content=message.content))

    llm_with_tools = get_llm().bind_tools(tools)

    for _ in range(MAX_TOOL_ROUNDS):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            content = response.content

            if isinstance(content, str) and content.strip():
                return content.strip()

            if isinstance(content, list):
                text_parts = [
                    item["text"]
                    for item in content
                    if isinstance(item, dict)
                    and isinstance(item.get("text"), str)
                ]
                answer = "\n".join(text_parts).strip()
                if answer:
                    return answer

            return "I couldn't generate an answer. Please try again."

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_call_id = tool_call["id"]
            tool = tools_by_name.get(tool_name)

            if tool is None:
                result = {"error": "Requested tool is unavailable"}
            else:
                try:
                    result = tool.invoke(tool_call["args"])
                except Exception:
                    # Keep internal errors in server logs, not in the AI response.
                    logger.exception("Admin chat tool execution failed")
                    result = {"error": "Tool execution failed"}

            messages.append(
                ToolMessage(
                    content=json.dumps(result, default=str),
                    tool_call_id=tool_call_id,
                )
            )

    return (
        "I couldn't complete the analysis within the allowed tool calls. "
        "Please narrow your question and try again."
    )