from django.db import models
from django.conf import settings


class Meeting(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PROCESSING = "processing", "Processing"
        TRANSCRIBED = "transcribed", "Transcribed"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=200)
    audio = models.FileField(upload_to="meetings/%Y/%m/")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    error = models.TextField(blank=True)
    transcript_json = models.JSONField(null=True, blank=True)  # segments with speakers + words
    summary = models.TextField(blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="meetings")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Note(models.Model):
    meeting = models.ForeignKey(Meeting, related_name="notes", on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)

    class Meta:
        ordering = ["created_at"]


class Export(models.Model):
    """Record of every place a transcript/summary was sent."""
    class Kind(models.TextChoices):
        TEXT = "text", "Text file"
        MARKDOWN = "markdown", "Markdown file"
        GDRIVE = "gdrive", "Google Drive file"

    meeting = models.ForeignKey(Meeting, related_name="exports", on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    target = models.CharField(max_length=300, blank=True)  # Drive file id / link
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)


class LiveSegment(models.Model):
    """Incremental transcript chunks from live recording preview."""
    meeting = models.ForeignKey(Meeting, related_name="live_segments", on_delete=models.CASCADE)
    seq = models.PositiveIntegerField()
    start = models.FloatField(default=0.0)
    end = models.FloatField(default=0.0)
    speaker = models.CharField(max_length=30, default="")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seq"]
        unique_together = [("meeting", "seq")]
