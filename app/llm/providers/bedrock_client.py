"""
bedrock_client.py — AWS Bedrock Converse API client using boto3.

Uses the official AWS SDK (boto3) for correct SigV4 signing.
Supports all Bedrock models (Claude, Nova, Llama, Mistral, Cohere, Titan)
via the unified Converse API.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any


class BedrockClient:
    """
    AWS Bedrock Converse API client backed by boto3.

    boto3 handles all SigV4 signing correctly, so no manual
    HMAC computation is needed.
    """

    def __init__(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
    ):
        self.access_key_id = access_key_id.strip()
        self.secret_access_key = secret_access_key.strip()
        self.region = (region or "us-east-1").strip()

    def _make_client(self):
        """Create a boto3 bedrock-runtime client with explicit credentials."""
        import boto3
        return boto3.client(
            "bedrock-runtime",
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
        )

    def _make_mgmt_client(self):
        """Create a boto3 bedrock management client (for listing/validation)."""
        import boto3
        return boto3.client(
            "bedrock",
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
        )

    def validate_credentials(self) -> None:
        """
        Validate AWS credentials by calling the Bedrock management API.

        Does NOT invoke any model — just confirms credentials are valid
        and the account has access to AWS Bedrock in the given region.

        Raises:
            RuntimeError: Clean, user-readable message on failure.
        """
        import botocore.exceptions

        try:
            mgmt = self._make_mgmt_client()
            # list_foundation_models only needs valid Bedrock credentials
            mgmt.list_foundation_models()
            return
        except botocore.exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            msg  = exc.response.get("Error", {}).get("Message", str(exc))

            if code in ("UnrecognizedClientException", "InvalidClientTokenId",
                        "InvalidSignatureException", "AuthFailure"):
                raise RuntimeError(
                    "Invalid AWS credentials. Please double-check your "
                    "Access Key ID and Secret Access Key."
                ) from exc

            if code == "AccessDeniedException":
                # Credentials are valid but the IAM user lacks
                # bedrock:ListFoundationModels — that's OK, fall through.
                return

            raise RuntimeError(
                f"AWS Bedrock validation failed ({code}): {msg}"
            ) from exc

        except botocore.exceptions.NoCredentialsError:
            raise RuntimeError("AWS credentials not found or empty.")

        except botocore.exceptions.EndpointResolutionError:
            raise RuntimeError(
                f"Cannot reach AWS Bedrock in region '{self.region}'. "
                "Check your region setting."
            )

        except Exception as exc:
            raise RuntimeError(
                f"Could not connect to AWS Bedrock: {exc}"
            ) from exc

    async def converse(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        timeout_seconds: float = 60,
    ) -> str:
        """
        Call the Bedrock Converse API.

        Args:
            model_id: e.g. "meta.llama3-70b-instruct-v1:0" or "anthropic.claude-3-5-sonnet-20241022-v2:0"
            messages: List of {"role": "user"/"assistant", "content": "text"}
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0–1)
            timeout_seconds: Request timeout in seconds

        Returns:
            The model's text response.

        Raises:
            RuntimeError: Clean, human-readable error message on failure.
        """
        # Build messages in Converse API format
        converse_messages = [
            {
                "role": msg["role"],
                "content": [{"text": msg["content"]}],
            }
            for msg in messages
            if msg["role"] in ("user", "assistant")
        ]

        def _do() -> str:
            import botocore.exceptions

            client = self._make_client()
            try:
                response = client.converse(
                    modelId=model_id,
                    messages=converse_messages,
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                )
            except botocore.exceptions.ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                msg = exc.response.get("Error", {}).get("Message", str(exc))

                if code in ("UnrecognizedClientException", "InvalidSignatureException", "AuthFailure"):
                    raise RuntimeError(
                        "Invalid AWS credentials. Please check your Access Key ID and Secret Access Key."
                    ) from exc
                if code == "AccessDeniedException":
                    raise RuntimeError(
                        f"Access denied. Make sure your IAM user/role has the 'bedrock:InvokeModel' "
                        f"permission and that model '{model_id}' is enabled in your Bedrock console "
                        f"under Model Access."
                    ) from exc
                if code == "ValidationException":
                    if "on-demand throughput" in msg or "inference profile" in msg.lower():
                        raise RuntimeError(
                            f"Model '{model_id}' requires an inference profile for on-demand use. "
                            f"Use the 'us.' prefixed version instead, e.g. 'us.{model_id}'. "
                            f"Select a model from the dropdown that starts with 'us.' (US Inference Profile)."
                        ) from exc
                    raise RuntimeError(f"Invalid request: {msg}") from exc
                if code == "ResourceNotFoundException":
                    raise RuntimeError(
                        f"Model '{model_id}' not found in region '{client.meta.region_name}'. "
                        f"Verify the model ID and that it's available in your region."
                    ) from exc
                if code == "ThrottlingException":
                    raise RuntimeError(
                        "AWS Bedrock request throttled. Please wait a moment and try again."
                    ) from exc
                raise RuntimeError(f"AWS Bedrock error ({code}): {msg}") from exc

            except botocore.exceptions.NoCredentialsError:
                raise RuntimeError("AWS credentials not found.")
            except botocore.exceptions.EndpointResolutionError:
                raise RuntimeError(
                    f"Could not reach AWS Bedrock in region '{self.region}'. "
                    f"Check your region setting."
                )
            except Exception as exc:
                # Catch connection errors etc. cleanly
                raise RuntimeError(f"Connection to AWS Bedrock failed: {exc}") from exc

            # Parse the Converse API response
            output = response.get("output") or {}
            message = output.get("message") or {}
            content_blocks = message.get("content") or []
            texts = [
                block["text"]
                for block in content_blocks
                if isinstance(block, dict) and block.get("text")
            ]
            return "\n".join(texts).strip()

        return await asyncio.to_thread(_do)
