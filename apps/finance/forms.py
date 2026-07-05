from django import forms

from .models import MaintenanceTicket


class MaintenanceTicketStatusForm(forms.ModelForm):
    class Meta:
        model = MaintenanceTicket
        fields = ("status",)
        widgets = {
            "status": forms.Select(
                attrs={
                    "class": (
                        "mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 "
                        "text-slate-100 focus:border-emerald-500 focus:outline-none focus:ring-1 "
                        "focus:ring-emerald-500"
                    )
                }
            ),
        }
