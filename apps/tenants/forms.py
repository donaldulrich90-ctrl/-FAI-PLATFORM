from django import forms
from django.utils.text import slugify

from apps.tenants.models import Tenant

_INPUT = (
    "mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 "
    "text-slate-100 placeholder-slate-500 focus:border-emerald-500 focus:outline-none "
    "focus:ring-1 focus:ring-emerald-500"
)
_CHECK = "h-4 w-4 rounded border-slate-600 bg-slate-950 text-emerald-600 focus:ring-emerald-500"


class TenantForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ("name", "slug", "is_active")
        help_texts = {
            "slug": "Lettres minuscules, chiffres et tirets. Laisser vide pour générer à partir du nom.",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT, "autocomplete": "organization"}),
            "slug": forms.TextInput(attrs={"class": _INPUT, "autocomplete": "off"}),
            "is_active": forms.CheckboxInput(attrs={"class": _CHECK}),
        }

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip()
        return slug

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("name") or "").strip()
        slug = (cleaned.get("slug") or "").strip()
        if name and not slug:
            base = slugify(name)[:60] or "organisation"
            candidate = base
            n = 0
            qs = Tenant.objects.all()
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            while qs.filter(slug=candidate).exists():
                n += 1
                candidate = f"{base}-{n}"
            cleaned["slug"] = candidate
        return cleaned
