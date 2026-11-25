"""Generate the thesis architecture diagrams as clean box-and-arrow PNGs,
styled to match the reference thesis (rounded boxes, muted palette, thin
black arrows)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D

GREEN = "#dcece2"; BLUE = "#dde7f0"; ORANGE = "#fbe3d4"; PURPLE = "#e8e2f0"
EDGE = "#4a4a4a"

def box(ax, x, y, w, h, text, color=GREEN, fontsize=9, weight="normal"):
    b = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.04",
                        linewidth=1.1, edgecolor=EDGE, facecolor=color)
    ax.add_patch(b)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center", fontsize=fontsize,
             weight=weight, wrap=True)
    return (x, y, w, h)

def arrow(ax, b1, b2, side1="right", side2="left"):
    x1,y1,w1,h1 = b1; x2,y2,w2,h2 = b2
    p1 = {"right": (x1+w1, y1+h1/2), "left": (x1, y1+h1/2),
          "bottom": (x1+w1/2, y1), "top": (x1+w1/2, y1+h1)}[side1]
    p2 = {"right": (x2+w2, y2+h2/2), "left": (x2, y2+h2/2),
          "bottom": (x2+w2/2, y2), "top": (x2+w2/2, y2+h2)}[side2]
    a = FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=12,
                         linewidth=1.1, color=EDGE)
    ax.add_patch(a)

def new_fig(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off")
    return fig, ax

# ---------------------------------------------------------------- Fig 3.1
fig, ax = new_fig(9, 2.6)
b1 = box(ax, 0.2, 0.9, 1.9, 0.9, "NF-CSE-CIC-\nIDS2018-v2\n(Parquet/CSV)", BLUE)
b2 = box(ax, 2.5, 0.9, 1.9, 0.9, "Data layer\nfilter, validate,\ndedup, sample, split", GREEN)
b3 = box(ax, 4.8, 0.9, 1.9, 0.9, "Feature layer\nratios, perturbation\nengine", GREEN)
b4 = box(ax, 7.1, 0.9, 1.7, 0.9, "Model layer\nM1 - M5\n(LightGBM)", ORANGE)
arrow(ax, b1, b2); arrow(ax, b2, b3); arrow(ax, b3, b4)
b5 = box(ax, 2.5, 0.0, 6.3, 0.6, "Evaluation layer: clean / moderate / OOD metrics, AER, SHAP drift audit", PURPLE, fontsize=8.5)
arrow(ax, b4, b5, "bottom", "right")
fig.tight_layout(); fig.savefig("fig_3_1_architecture.png", dpi=220); plt.close(fig)

# ---------------------------------------------------------------- Fig 3.2 (pipeline)
fig, ax = new_fig(9, 1.6)
steps = ["Filter\n(4 classes)", "Validate\n(finite, >=0)", "Deduplicate\n(hash)", "Stratified\nsample", "Train/test\nsplit", "Model-specific\ntransforms"]
bxs = []
wgap = 9.0/len(steps)
for i, s in enumerate(steps):
    bxs.append(box(ax, i*wgap+0.1, 0.5, wgap-0.2, 0.9, s, GREEN, fontsize=8))
for i in range(len(bxs)-1):
    arrow(ax, bxs[i], bxs[i+1])
fig.tight_layout(); fig.savefig("fig_3_2_pipeline.png", dpi=220); plt.close(fig)

# ---------------------------------------------------------------- Fig 3.3 (model progression)
fig, ax = new_fig(9, 3.2)
m1 = box(ax, 0.2, 2.4, 1.6, 0.7, "M1\nBaseline\n(40 feat.)", BLUE)
m2 = box(ax, 2.1, 2.4, 1.6, 0.7, "M2\nNo-timing\n(33 feat.)", BLUE)
m3 = box(ax, 4.0, 2.4, 1.6, 0.7, "M3\nGaussian\nnoise", ORANGE)
m4 = box(ax, 5.9, 2.4, 1.6, 0.7, "M4\nAdversarial\npacing", ORANGE)
m5 = box(ax, 7.3, 1.1, 1.6, 0.7, "M5\nSHAP-guided\nhybrid", PURPLE)
shap = box(ax, 4.0, 1.1, 2.4, 0.7, "SHAP selection on M1\n(fragile timing cols removed)", GREEN, fontsize=8)
ratios = box(ax, 0.2, 1.1, 2.9, 0.7, "+8 engineered timing-\ninvariant ratios", GREEN, fontsize=8)
arrow(ax, m1, shap, "bottom", "top")
arrow(ax, shap, m5, "right", "top")
arrow(ax, ratios, m5, "right", "left")
arrow(ax, m4, m5, "bottom", "top")
fig.tight_layout(); fig.savefig("fig_3_3_progression.png", dpi=220); plt.close(fig)

# ---------------------------------------------------------------- Fig 4.1 (perturbation workflow)
fig, ax = new_fig(9, 2.6)
b1 = box(ax, 0.2, 1.0, 1.8, 0.9, "Clean test flow\n(attack class)", BLUE)
b2 = box(ax, 2.4, 1.0, 1.9, 0.9, "Draw alpha ~\nU(lo, hi) per flow", GREEN)
b3 = box(ax, 4.7, 1.0, 2.0, 0.9, "Duration cols x alpha\nRate cols / alpha\n(if approved)", ORANGE, fontsize=8)
b4 = box(ax, 7.1, 1.0, 1.7, 0.9, "Structural cols\nheld fixed", PURPLE)
arrow(ax, b1, b2); arrow(ax, b2, b3); arrow(ax, b3, b4)
b5 = box(ax, 2.4, 0.0, 6.4, 0.6, "Consistency verification: 9 invariants (bytes/packets fixed, duration scaling, ratio invariance, zero-duration, no NaN/Inf)", GREEN, fontsize=7.5)
arrow(ax, b4, b5, "bottom", "right")
fig.tight_layout(); fig.savefig("fig_4_1_perturbation.png", dpi=220); plt.close(fig)

# ---------------------------------------------------------------- Fig 4.2 (SHAP selection)
fig, ax = new_fig(9, 3.0)
b1 = box(ax, 0.2, 2.1, 2.0, 0.7, "Train M1 (seed 42)\non clean pool", BLUE)
b2 = box(ax, 2.6, 2.1, 2.3, 0.7, "Class-capped subset\n(<=2500/class)", GREEN)
b3 = box(ax, 5.3, 2.1, 2.1, 0.7, "shap.TreeExplainer\n(raw margin)", GREEN)
b4 = box(ax, 7.8, 2.1, 1.1, 0.7, "I_j share", GREEN, fontsize=8)
arrow(ax, b1, b2); arrow(ax, b2, b3); arrow(ax, b3, b4)
b5 = box(ax, 5.3, 0.9, 3.6, 0.7, "Flag fragile if I_j >= 1/p (p=40, thr=0.025)", ORANGE, fontsize=8)
arrow(ax, b4, b5, "bottom", "top")
b6 = box(ax, 0.2, 0.9, 4.6, 0.7, "M5 layer = structural + unflagged timing + 8 engineered ratios (frozen)", PURPLE, fontsize=8)
arrow(ax, b5, b6, "left", "right")
fig.tight_layout(); fig.savefig("fig_4_2_shap_selection.png", dpi=220); plt.close(fig)

# ---------------------------------------------------------------- Fig 4.3 (M5 hybrid architecture)
fig, ax = new_fig(9, 2.8)
l1 = box(ax, 0.3, 1.5, 4.0, 1.0, "Layer 1: Timing-invariant feature layer\n(33 structural + unflagged timing + 8 ratios)", GREEN, fontsize=8)
l2 = box(ax, 4.9, 1.5, 4.0, 1.0, "Layer 2: Adversarial data layer\nclean pool + 1 slowed copy / attack flow", ORANGE, fontsize=8)
out = box(ax, 2.6, 0.2, 4.0, 0.8, "M5: SHAP-guided two-layer hybrid defence\n(LightGBM, class_weight='balanced')", PURPLE, fontsize=8.5)
arrow(ax, l1, out, "bottom", "top")
arrow(ax, l2, out, "bottom", "top")
fig.tight_layout(); fig.savefig("fig_4_3_m5_hybrid.png", dpi=220); plt.close(fig)

# ---------------------------------------------------------------- Fig 4.4 (evaluation workflow)
fig, ax = new_fig(9, 2.2)
b1 = box(ax, 0.2, 0.6, 1.9, 0.9, "5 seeds:\ntrain M1-M5", BLUE)
b2 = box(ax, 2.5, 0.6, 2.0, 0.9, "Predict on clean /\nmoderate / OOD", GREEN)
b3 = box(ax, 5.0, 0.6, 1.9, 0.9, "AER, recall,\nmean +/- std", ORANGE)
b4 = box(ax, 7.3, 0.6, 1.6, 0.9, "SHAP drift\naudit", PURPLE)
arrow(ax, b1, b2); arrow(ax, b2, b3); arrow(ax, b3, b4)
fig.tight_layout(); fig.savefig("fig_4_4_eval_workflow.png", dpi=220); plt.close(fig)

print("done")
