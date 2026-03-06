-- token_bucket.lua
-- KEYS[1]: rate limit key
-- ARGV[1]: max_tokens (bucket capacity)
-- ARGV[2]: refill_rate (tokens per second)
-- ARGV[3]: now (current timestamp as float)
-- ARGV[4]: tokens_to_consume (default 1)
-- ARGV[5]: ttl (key expiry in seconds)
-- Returns: {allowed(0/1), remaining_tokens, retry_after_ms}

local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local consume = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call('GET', key)
local tokens, last_refill

if data then
    local t = cjson.decode(data)
    tokens = t.tokens
    last_refill = t.last_refill
else
    tokens = max_tokens
    last_refill = now
end

-- Refill
local elapsed = now - last_refill
local new_tokens = elapsed * refill_rate
tokens = math.min(max_tokens, tokens + new_tokens)
last_refill = now

-- Consume
if tokens >= consume then
    tokens = tokens - consume
    redis.call('SET', key, cjson.encode({tokens=tokens, last_refill=last_refill}), 'EX', ttl)
    return {1, math.floor(tokens * 1000) / 1000, 0}
else
    local wait = (consume - tokens) / refill_rate
    redis.call('SET', key, cjson.encode({tokens=tokens, last_refill=last_refill}), 'EX', ttl)
    return {0, math.floor(tokens * 1000) / 1000, math.ceil(wait * 1000)}
end
