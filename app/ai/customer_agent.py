
import json
import logging

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import get_llm
from app.ai.customer_prompts import get_customer_system_message
from app.ai.tools.customer_product_tools import (
    create_customer_product_tools,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
MAX_HISTORY_MESSAGES = 12

SHOPPING_TOOL_NAMES = {
    "search_shoes",
    "get_product_details",
    "add_to_cart",
    "get_cart",
    "update_cart_item",
    "remove_from_cart",
    "place_order",
}


async def run_customer_agent(
    db: AsyncSession,
    history: list,
    cart=None,
    current_user=None,
    confirmation_authorized: bool = False,
) -> tuple[str, list[dict]]:
    """
    Run the asynchronous customer shopping agent.

    Args:
        db: Asynchronous database session.
        history: Recent messages for this conversation.
        cart: Cart resolved by the backend.
        current_user: Authenticated user resolved by FastAPI.
        confirmation_authorized: Must be verified by the backend.

    Returns:
        Assistant reply and structured product cards.
    """

    tools = create_customer_product_tools(
        db=db,
        cart=cart,
        current_user=current_user,
        confirmation_authorized=confirmation_authorized,
    )

    tools_by_name = {
        selected_tool.name: selected_tool
        for selected_tool in tools
    }

    messages = [get_customer_system_message()]

    # Restore recent conversation context.
    for message in history[-MAX_HISTORY_MESSAGES:]:

        if message.role == "user":
            messages.append(
                HumanMessage(content=message.content)
            )

        elif message.role == "assistant":
            messages.append(
                AIMessage(content=message.content)
            )

    llm_with_tools = get_llm().bind_tools(tools)

    # Product cards returned to the frontend.
    found_products: dict[int, dict] = {}
    executed_adds: dict[tuple[int, int, int | None], dict] = {}

    for _ in range(MAX_TOOL_ROUNDS):

        # Asynchronous LLM execution.
        response = await llm_with_tools.ainvoke(messages)

        messages.append(response)

        # The model has finished its response.
        if not response.tool_calls:

            content = response.content

            if isinstance(content, str):
                answer = content.strip()

            elif isinstance(content, list):
                answer = "\n".join(
                    item["text"]
                    for item in content
                    if isinstance(item, dict)
                    and isinstance(item.get("text"), str)
                ).strip()

            else:
                answer = ""

            if not answer:
                answer = (
                    "I couldn't prepare a reply. Please try again."
                )

            return answer, list(found_products.values())

        # Execute requested tools sequentially.
        # Do not run these concurrently using the same AsyncSession.
        for tool_call in response.tool_calls:

            tool_name = tool_call["name"]
            tool_call_id = tool_call["id"]

            selected_tool = tools_by_name.get(tool_name)

            if (
                selected_tool is None
                or tool_name not in SHOPPING_TOOL_NAMES
            ):
                result = {
                    "success": False,
                    "error": "Requested tool is unavailable.",
                }

            elif (
                tool_name == "place_order"
                and not confirmation_authorized
            ):
                result = {
                    "success": False,
                    "message": (
                        "Order confirmation has not been authorized "
                        "by the backend. Ask the customer to confirm "
                        "the checkout summary."
                    ),
                }

            elif (
                tool_name == "place_order"
                and current_user is None
            ):
                result = {
                    "success": False,
                    "message": (
                        "Please log in before placing an order."
                    ),
                }

            else:
                try:
                    tool_args = tool_call["args"]

                    if tool_name == "add_to_cart":
                        add_key = (
                            int(tool_args["product_id"]),
                            int(tool_args.get("quantity", 1)),
                            (
                                int(tool_args["variant_id"])
                                if tool_args.get("variant_id") is not None
                                else None
                            ),
                        )

                        if add_key in executed_adds:
                            result = executed_adds[add_key]
                        else:
                            result = await selected_tool.ainvoke(tool_args)
                            executed_adds[add_key] = result
                    else:
                        # Asynchronous LangChain tool execution.
                        result = await selected_tool.ainvoke(tool_args)

                    if not isinstance(result, dict):
                        result = {
                            "success": False,
                            "error": (
                                "Tool returned an unexpected result."
                            ),
                        }

                    # Collect product cards from searches.
                    if (
                        tool_name == "search_shoes"
                        and not result.get("error")
                    ):
                        for product in result.get("products", []):

                            product_id = product.get("id")

                            if product_id is not None:
                                found_products[product_id] = product

                    # Collect product cards from detail lookup.
                    elif tool_name == "get_product_details":

                        product = result.get("product")

                        if (
                            result.get("success")
                            and isinstance(product, dict)
                            and product.get("id") is not None
                        ):
                            found_products[product["id"]] = product

                except Exception:
                    logger.exception(
                        "Customer shopping tool '%s' failed",
                        tool_name,
                    )

                    result = {
                        "success": False,
                        "error": (
                            f"The {tool_name} operation failed. "
                            "Do not claim it succeeded."
                        ),
                    }

            # Give the actual tool result back to the model.
            messages.append(
                ToolMessage(
                    content=json.dumps(result, default=str),
                    tool_call_id=tool_call_id,
                )
            )

    return (
        "I couldn't complete that shopping request. "
        "Please try again or make your request more specific.",
        list(found_products.values()),
    )
