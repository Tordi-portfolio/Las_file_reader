import json
import pandas as pd
import lasio
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from .forms import UploadLASForm
from .models import UploadedLAS


def _read_las_from_storage(file_field):
    """Read LAS file from UploadedLAS.file and return (lasio.LASFile, DataFrame)."""
    fpath = file_field.path
    las = lasio.read(fpath, ignore_data=False, read_policy="default")
    df = las.df()  # Depth/index becomes DataFrame index
    if df.index.name is None:
        df.index.name = las.index_unit or "INDEX"
    return las, df


@require_http_methods(["GET", "POST"])
def home(request):
    """Upload LAS file and redirect to viewer."""
    form = UploadLASForm()
    if request.method == "POST":
        form = UploadLASForm(request.POST, request.FILES)
        if form.is_valid():
            obj = form.save()
            return redirect("logs:view_las", pk=obj.pk)
    return render(request, "logs/home.html", {"form": form})


def view_las(request, pk: int):
    """Display LAS metadata and curves list."""
    obj = get_object_or_404(UploadedLAS, pk=pk)
    try:
        las, df = _read_las_from_storage(obj.file)
    except Exception as e:
        return render(request, "logs/error.html", {"error": str(e)})

    well_info = {item.mnemonic: str(item.value) for item in las.well}
    params = {item.mnemonic: str(item.value) for item in las.params}

    curves = []
    index_name = df.index.name or "INDEX"

    for c in las.curves:
        # Check if this curve is actually the DataFrame index
        if c.mnemonic == index_name:
            col_data = pd.Series(df.index)
        elif c.mnemonic in df.columns:
            col_data = df[c.mnemonic]
        else:
            # Skip missing curve
            continue

        curves.append({
            "mnemonic": c.mnemonic,
            "unit": c.unit or "",
            "descr": c.descr or "",
            "min": float(pd.to_numeric(col_data, errors="coerce").min()),
            "max": float(pd.to_numeric(col_data, errors="coerce").max()),
            "null": las.null if hasattr(las, "null") else None,
        })

    context = {
        "obj": obj,
        "well_info": well_info,
        "params": params,
        "curves": curves,
        "index_label": index_name,
    }
    return render(request, "logs/view.html", context)


def curve_api(request, pk: int, curve_mnemonic: str):
    """Return JSON curve data for Plotly chart."""
    obj = get_object_or_404(UploadedLAS, pk=pk)
    try:
        las, df = _read_las_from_storage(obj.file)
    except Exception:
        raise Http404("LAS could not be read")

    index_name = df.index.name or "INDEX"

    if curve_mnemonic == index_name:
        series = pd.Series(df.index)
    elif curve_mnemonic in df.columns:
        series = df[curve_mnemonic]
    else:
        raise Http404("Curve not found")

    idx = df.index

    # Downsample for speed
    max_points = 5000
    if len(series) > max_points:
        step = len(series) // max_points
        series = series[::step]
        idx = idx[::step]

    data = {
        "index_label": index_name,
        "curve": curve_mnemonic,
        "x": idx.astype(float).tolist(),   # depth/index
        "y": pd.to_numeric(series, errors="coerce").astype(float).tolist(),
    }
    return JsonResponse(data)
