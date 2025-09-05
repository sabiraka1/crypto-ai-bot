"""
Trace ID management for distributed tracing and correlation.

Provides context-safe trace ID propagation across async operations.
Integrates with logging system for automatic correlation.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from crypto_ai_bot.utils.logging import (
    get_correlation_id as _get_log_cid,
    set_correlation_id as _set_log_cid,
)

# Context variable for correlation ID (async-safe)
_CID: ContextVar[Optional[str]] = ContextVar("cid", default=None)

# Trace ID format prefix (optional, for filtering)
TRACE_PREFIX = "trace_"


def generate_trace_id(prefix: str = "") -> str:
    """
    Generate new unique trace ID.
    
    Args:
        prefix: Optional prefix for the trace ID
        
    Returns:
        Unique trace ID (UUID hex format)
        
    Examples:
        generate_trace_id() -> "a1b2c3d4e5f6..."
        generate_trace_id("order_") -> "order_a1b2c3d4e5f6..."
    """
    uid = uuid.uuid4().hex
    return f"{prefix}{uid}" if prefix else uid


def set_trace_id(value: Optional[str]) -> None:
    """
    Set trace ID in context and logger.
    
    Args:
        value: Trace ID to set (None to clear)
    """
    _CID.set(value)
    _set_log_cid(value)


def get_trace_id() -> Optional[str]:
    """
    Get current trace ID from context or logger.
    
    Returns:
        Current trace ID or None if not set
    """
    # First try context variable, then logger
    return _CID.get() or _get_log_cid()


def clear_trace_id() -> None:
    """Clear trace ID from context and logger"""
    set_trace_id(None)


@contextmanager
def trace_context(trace_id: Optional[str] = None, prefix: str = "") -> Iterator[str]:
    """
    Context manager for trace ID propagation.
    
    Ensures trace ID is properly set and cleaned up after use.
    Integrates with logging system for automatic correlation.
    
    Usage:
        # Auto-generate trace ID
        with trace_context() as tid:
            log.info("Processing", extra={"trace_id": tid})
            
        # Use existing trace ID
        with trace_context("existing_id") as tid:
            await process_order(tid)
    
    Args:
        trace_id: Optional trace ID to use. If None, generates new one.
        prefix: Prefix for generated trace ID (ignored if trace_id provided)
        
    Yields:
        The trace ID being used in this context
    """
    # Save current state
    current = get_trace_id()
    
    # Set new trace ID
    new_value = trace_id or generate_trace_id(prefix)
    token = _CID.set(new_value)
    _set_log_cid(new_value)
    
    try:
        yield new_value
    finally:
        # Restore previous state
        _CID.reset(token)
        _set_log_cid(current)


@contextmanager
def nested_trace_context(parent_id: Optional[str] = None, separator: str = ".") -> Iterator[str]:
    """
    Create nested trace context with parent-child relationship.
    
    Useful for sub-operations that need their own trace but should
    maintain relationship to parent operation.
    
    Usage:
        with trace_context() as parent_tid:
            # Main operation
            with nested_trace_context(parent_tid) as child_tid:
                # Sub-operation with trace like "parent_id.child_id"
                
    Args:
        parent_id: Parent trace ID. If None, uses current context.
        separator: Separator between parent and child IDs
        
    Yields:
        Combined trace ID (parent.child format)
    """
    parent = parent_id or get_trace_id()
    child_suffix = uuid.uuid4().hex[:8]  # Shorter for nested
    
    if parent:
        nested_id = f"{parent}{separator}{child_suffix}"
    else:
        nested_id = child_suffix
        
    with trace_context(nested_id) as tid:
        yield tid


def with_trace_id(func):
    """
    Decorator to automatically add trace context to async functions.
    
    Usage:
        @with_trace_id
        async def process_order(order_id: str):
            # Automatically has trace context
            log.info(f"Processing {order_id}")
            
    Args:
        func: Async function to wrap
        
    Returns:
        Wrapped function with automatic trace context
    """
    import functools
    import asyncio
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Check if trace_id passed as kwarg
        trace_id = kwargs.pop('trace_id', None)
        
        # Use existing context or create new
        if get_trace_id() and not trace_id:
            # Already in trace context, just run
            return await func(*args, **kwargs)
        else:
            # Create new trace context
            with trace_context(trace_id) as tid:
                # Add trace_id back to kwargs if function expects it
                import inspect
                sig = inspect.signature(func)
                if 'trace_id' in sig.parameters:
                    kwargs['trace_id'] = tid
                return await func(*args, **kwargs)
                
    return wrapper


# ============= BACKWARD COMPATIBILITY =============
# Keep old names for compatibility with existing code

set_cid = set_trace_id
get_cid = get_trace_id
cid_context = trace_context


# ============= UTILITIES =============

def format_trace_id(trace_id: Optional[str], max_length: int = 8) -> str:
    """
    Format trace ID for display (truncated).
    
    Args:
        trace_id: Full trace ID
        max_length: Maximum length for display (must be positive)
        
    Returns:
        Formatted trace ID for logging/display
        
    Examples:
        format_trace_id("a1b2c3d4e5f6...") -> "a1b2c3d4"
        format_trace_id(None) -> "no-trace"
    """
    if not trace_id:
        return "no-trace"
    
    # Protect against invalid max_length
    if max_length <= 0:
        return "no-trace"
    
    if len(trace_id) <= max_length:
        return trace_id
        
    return trace_id[:max_length]


def is_valid_trace_id(trace_id: str) -> bool:
    """
    Check if string is a valid trace ID format.
    
    Args:
        trace_id: String to validate
        
    Returns:
        True if valid trace ID format
    """
    if not trace_id:
        return False
        
    # Basic validation: should be hex characters (possibly with prefix)
    # Strip common prefixes
    test_id = trace_id
    for prefix in [TRACE_PREFIX, "order_", "trade_", "recon_"]:
        if test_id.startswith(prefix):
            test_id = test_id[len(prefix):]
            break
            
    # Check if remaining is valid hex
    try:
        int(test_id, 16)
        return len(test_id) in [32, 8, 16]  # UUID hex lengths
    except ValueError:
        return False


# ============= EXPORT =============

__all__ = [
    # Main functions
    "generate_trace_id",
    "set_trace_id",
    "get_trace_id",
    "clear_trace_id",
    
    # Context managers
    "trace_context",
    "nested_trace_context",
    
    # Decorator
    "with_trace_id",
    
    # Utilities
    "format_trace_id",
    "is_valid_trace_id",
    
    # Constants
    "TRACE_PREFIX",
    
    # Backward compatibility
    "set_cid",
    "get_cid",
    "cid_context",
]