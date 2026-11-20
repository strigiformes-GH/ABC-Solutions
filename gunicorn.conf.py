import os


bind = "0.0.0.0:" + os.getenv("PORT", "8000")
workers = 1
threads = 4
timeout = 60
accesslog = "-"
errorlog = "-"
# query strings can contain tokens
access_log_format = '%(t)s %(m)s %(U)s %(s)s %(b)s'
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
