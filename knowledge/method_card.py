"""
方法卡片数据模型与序列化

参照方案 §4.2 + 附录A 方法卡片模板格式。
"""


METHOD_CARD_TEMPLATE = """
method:
  name: "{method_name}"
  type: {method_type}          # solver/filter/projection/optimizer/controller/evaluator
  status: {status}             # candidate/experimental/verified/deprecated

problem:
  description: "{problem}"
  reference: "{reference}"

formula:
  source_page: {page}
  source_equation: "{equation}"
  content: >
    {formula_text}

parameters:
{parameters}

conditions:
  applicable: {applicable_conditions}
  known_risks: {known_risks}

evidence:
  doi: "{doi}"
  pages: {pages}
  figures: {figures}

verification:
  unit_test: {unit_test}
  finite_difference: {finite_difference}
  benchmark_mbb: {benchmark_mbb}
  benchmark_3d: {benchmark_3d}
  cpu_gpu_consistency: {cpu_gpu_consistency}
  verified_by: "{verified_by}"
"""


def format_method_card(**kwargs) -> str:
    """格式化方法卡片为 YAML 字符串"""
    params_yaml = ""
    for p in kwargs.get("parameters", []):
        params_yaml += f"  - name: {p['name']}\n    meaning: \"{p['meaning']}\"\n"
        if "suggested" in p:
            params_yaml += f"    suggested: {p['suggested']}\n"
        if "range" in p:
            params_yaml += f"    range: {p['range']}\n"

    return METHOD_CARD_TEMPLATE.format(
        parameters=params_yaml or "  []",
        **kwargs
    )