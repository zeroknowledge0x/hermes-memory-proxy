# Example: Hermes cron jobs for self-improvement loops
#
# Run from the host where Hermes is installed. These keep memory tidy
# (consolidate facts → durable profile; score importance for better ranking).
# Use a FLAT prompt — do NOT use brain_loop(...) here.

hermes cron create "every 6h" \
  "POST http://127.0.0.1:8899/v1/consolidate?user=<your-id>" \
  --name loop_memory_consolidate

hermes cron create "every 3h" \
  "POST http://127.0.0.1:8899/v1/reflect?user=<your-id>" \
  --name loop_memory_reflect

# Optional: expire exact-duplicate facts + keep one consolidated profile
hermes cron create "every 12h" \
  "POST http://127.0.0.1:8899/v1/admin/dedupe?user=<your-id>" \
  --name loop_memory_dedupe
