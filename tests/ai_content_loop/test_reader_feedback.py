from ai_content_loop.editorial.reader_feedback import evaluate_reader_feedback


def dimension(result, key):
    return next(item for item in result["dimensions"] if item["key"] == key)


def test_reader_feedback_has_five_explainable_dimensions_and_priority():
    body = (
        "晚上十一点，你还在给第十条短视频找素材。一个新工具把文案、配音和粗剪串到了一起，"
        "但它省下的究竟是时间，还是把成本挪到了 API？\n\n"
        "简单说，它先生成脚本，再匹配素材，最后输出带字幕的初版视频。以前要在三个软件之间"
        "来回复制，现在可以少做两次搬运。\n\n"
        "真正的关键不是一键生成，而是谁来承担最后的返工。先拿一个低风险选题测试，再比较"
        "人工时间、接口支出和修改次数。\n\n"
        "自动化没有消灭成本，只是让你决定：把成本留给重复劳动，还是交给 API 和最后一次校对。"
    )

    result = evaluate_reader_feedback("短视频流水线把成本挪到了哪里", body)

    assert result["version"] == "reader-feedback-v1"
    assert [item["key"] for item in result["dimensions"]] == [
        "hook",
        "comprehension",
        "emotion",
        "value",
        "ending",
    ]
    assert all(0 <= item["score"] <= 5 for item in result["dimensions"])
    assert all(item["evidence"] for item in result["dimensions"])
    assert all(item["suggestion"] for item in result["dimensions"])
    assert result["overall"] == round(
        sum(item["score"] for item in result["dimensions"]) / 5,
        1,
    )
    assert result["priority"]["key"] in {
        item["key"] for item in result["dimensions"]
    }


def test_reader_feedback_penalizes_flat_opening_and_weak_meta_ending():
    body = (
        "最近有个变化值得普通读者看一眼。这个项目提供了很多功能，具有一定参考价值。\n\n"
        "项目使用模型、参数、benchmark、embedding、RAG、Agent 和 API 完成相关处理。\n\n"
        "总的来说，这是我的判断（个人观点），后续值得持续观察。\n\n"
        "来源：https://example.com/source"
    )

    result = evaluate_reader_feedback("一个项目的相关介绍", body)

    assert dimension(result, "hook")["score"] <= 2.5
    assert dimension(result, "emotion")["score"] <= 2.5
    assert dimension(result, "ending")["score"] <= 2.0
    assert "值得持续观察" in dimension(result, "ending")["evidence"]


def test_reader_feedback_rewards_splitting_a_text_wall_without_changing_content():
    sentence = "模型先读取截图，再定位按钮，最后执行操作，但关键数字仍然可能识别错误。"
    wall = sentence * 10
    split = "\n\n".join(sentence * 2 for _index in range(5))

    wall_result = evaluate_reader_feedback("AI 为什么总是点错按钮", wall)
    split_result = evaluate_reader_feedback("AI 为什么总是点错按钮", split)

    assert dimension(split_result, "comprehension")["score"] > dimension(
        wall_result,
        "comprehension",
    )["score"]
    assert "最长段" in dimension(wall_result, "comprehension")["evidence"]


def test_reader_feedback_rewards_a_concrete_decision_rule():
    dry = (
        "这个工具可以生成内容。\n\n"
        "它也有一些限制。\n\n"
        "这个项目具有一定价值。"
    )
    useful = (
        "这个工具可以生成内容。\n\n"
        "它把人工时间换成接口支出，失败后仍然需要人返工。\n\n"
        "先用一个低风险任务验证输入和输出；如果关键步骤仍需手工补齐，就不要迁移正式流程。"
    )

    dry_result = evaluate_reader_feedback("这个工具能不能投入工作", dry)
    useful_result = evaluate_reader_feedback("这个工具能不能投入工作", useful)

    assert dimension(useful_result, "value")["score"] > dimension(
        dry_result,
        "value",
    )["score"]
    assert dimension(useful_result, "ending")["score"] > dimension(
        dry_result,
        "ending",
    )["score"]


def test_reader_feedback_ignores_the_source_line_when_scoring_the_ending():
    ending = "在它学会看清数字之前，别急着让它替你碰钱、合同和客户。"
    without_source = evaluate_reader_feedback(
        "AI 看截图为什么总点错按钮",
        f"AI 看见了按钮，却读错了数字。\n\n{ending}",
    )
    with_source = evaluate_reader_feedback(
        "AI 看截图为什么总点错按钮",
        f"AI 看见了按钮，却读错了数字。\n\n{ending}\n\n来源：https://example.com",
    )

    assert dimension(with_source, "ending") == dimension(without_source, "ending")
