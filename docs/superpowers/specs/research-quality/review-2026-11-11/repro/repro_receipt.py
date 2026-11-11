from clue_api.arv2.quality_provider_tools import receipt_preview
value = {"state": "complete", "gaps": ["youtube_data HTTP 403"], "n_results": 0,
         "report": "0 video results from 2 searches. Read the overview at the top of result_path ...",
         "overview": [], "videos": []}
hits, count, empty = receipt_preview(value)
print("empty:", empty, "count:", count)
print(hits)
