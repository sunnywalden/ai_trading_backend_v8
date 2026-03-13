from app.services.non_realtime_data_policy import NonRealtimeDataPolicyService


def test_runtime_signal_generation_policy_defaults_to_cache_only():
    policy = NonRealtimeDataPolicyService.runtime_signal_generation()

    assert policy.context == "runtime_signal_generation"
    assert policy.historical_cache_only is True
    assert policy.key_statistics_cache_only is True
    assert policy.fundamental_cache_only is True


def test_scheduled_refresh_policy_allows_live_fetch():
    policy = NonRealtimeDataPolicyService.scheduled_refresh()

    assert policy.context == "scheduled_refresh"
    assert policy.historical_cache_only is False
    assert policy.key_statistics_cache_only is False
    assert policy.fundamental_cache_only is False