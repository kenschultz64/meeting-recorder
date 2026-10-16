from django.contrib import admin
from .models import Export, Meeting, Note


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "duration_sec", "created_at")
    list_filter = ("status",)
    search_fields = ("title",)


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("meeting", "created_at")


@admin.register(Export)
class ExportAdmin(admin.ModelAdmin):
    list_display = ("meeting", "kind", "target", "created_at")
