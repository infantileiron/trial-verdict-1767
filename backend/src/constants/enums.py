ROLES=('admin','analyst','viewer')
GROUPS=('A','B')
EVENT_KINDS=('exposure','activation')
STATES=('queued','running','done','failed')
ACTIONS=('publish_b','keep_a')
# 别名关联任务与任务项复用 queued/running/done/failed
ALIAS_JOB_STATES=('queued','running','done','failed')
ALIAS_ITEM_STATES=('pending','done','failed','skipped')
