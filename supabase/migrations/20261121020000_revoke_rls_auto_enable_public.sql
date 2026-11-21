-- Pre-existing SECURITY DEFINER helper was callable by anon/authenticated via RPC; backend does not use it.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
