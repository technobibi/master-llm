def format_log(record):
    # record: {'level':str, 'ts':str, 'message':str}
    # '[LEVEL] ts message' 形式。LEVEL は大文字右詰め5桁
    return record['message']
