from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=True,
    excluded_handlers=["/metrics", "/api/v1/health"],
    env_var_name="ENABLE_METRICS",
)
