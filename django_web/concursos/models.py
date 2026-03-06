from django.db import models


class Opportunity(models.Model):
    hash_id = models.TextField(unique=True)
    source = models.TextField()
    notice_number = models.TextField(null=True, blank=True)
    title = models.TextField()
    description = models.TextField(null=True, blank=True)
    entity = models.TextField(null=True, blank=True)
    country = models.TextField(null=True, blank=True)
    location = models.TextField(null=True, blank=True)
    cpv = models.TextField(null=True, blank=True)
    estimated_value = models.TextField(null=True, blank=True)
    criterion = models.TextField(null=True, blank=True)
    published_at = models.TextField(null=True, blank=True)
    deadline_at = models.TextField(null=True, blank=True)
    link = models.TextField()
    category = models.TextField(null=True, blank=True)
    relevance_score = models.IntegerField(default=0)
    status = models.TextField(default="new")
    feedback_note = models.TextField(null=True, blank=True)
    first_seen_at = models.TextField()
    last_seen_at = models.TextField()

    class Meta:
        managed = False
        db_table = "opportunities"
