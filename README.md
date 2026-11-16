# 广告曝光有效性与费用结算

按曝光ID裁决重复与冲突，按时间及ID确定日频次，再聚合有效CPM。冲销引用采信的原曝光，同一曝光最多冲销一次，费用回到原曝光账日。

使用者按采信、规则复算、异常复核和归档顺序处理一批数据。启动后自动装入异常样例，切换基准样例可比较两者结论。

## 启动与测试
```sh
docker compose up --build -d
docker compose exec -T app pytest -q
docker compose config --quiet
```

浏览器打开 [工作台](http://localhost:18205)。

## 业务模块

- 日志采信：读取曝光和冲销台账，入口 `/intake` 与 `GET /api/intake`。
- 计费契约：核查曝光ID、时区和渠道资费，入口 `/contract` 与 `GET /api/contract`。
- 有效性判定：排除机器曝光与超过频次事件，入口 `/model` 与 `GET /api/model`。
- 费用聚合：按渠道账日结算并核查冲销限额，入口 `/calculate` 与 `GET /api/calculate`。
- 争议隔离：定位冲突和无法合法冲销事件，入口 `/quarantine` 与 `GET /api/quarantine`。
- 渠道对账：逐渠道复算账单差额，入口 `/reconcile` 与 `GET /api/reconcile`。
- 批次复核：幂等重算与版本归档，入口 `/batches` 与 `GET /api/batches`。
- 账期裁决：关账冻结原账，迟到记录与冲销的差额由本期承担，入口 `/periods`。

## 演示
选择样例后运行，核对业务结论与来源行。异常行保留原值和原因码。复核提交使用当前版本；旧版本返回 409。CSV证据只保留一个归档入口。
账期页先对 2026-11 关账冻结原账 0.69 元，再用“迟到记录与冲销”样例补交：页面分渠道展示原账应付、差额来源与本次正式应付，非法记录进入隔离且行数守恒；同批重复提交不新增版本，错误提交提示后旧版保留。

## API
- `POST /api/runs`：JSON 中可指定 `sample`、`text` 与 `params`。
- `POST /api/runs/{run_id}/review`：提交 `revision`、`decision`。
- `GET /api/runs/{run_id}/evidence.csv`：来源证据。
- `POST /api/periods/close`：关账并冻结已发布账期金额（`period`、`current_period`）。
- `POST /api/periods/supplements`：提交迟到记录与冲销补交，裁决差额入账期。
- `POST /api/periods/supplements/{id}/review`：补交批次复核，陈旧 `revision` 返回 409。
- `GET /docs`：接口定义。

## 账期裁决原则
关账后原账期金额冻结且一直可查，任何迟到曝光与迟到冲销都不回写原账期：其差额（迟到新增减迟到扣减）全部计入当前账期，本次正式应付＝本期自身净额＋关账期差额，差额在页面逐渠道、逐来源行可追溯，不设无限挂账。补交批次按内容、账期与关账摘要生成幂等摘要：同批重试只返回同一条待复核记录，不新增版本；处理失败整体回滚，旧版本与全部来源记录保留。重复补报、重复冲销、无效引用与账期外记录进入隔离，保留来源行且不产生金额。

## 数据保存
SQLite 位于命名卷 records。相同内容、参数与规则版本只产生一条运行记录。仅需重启时执行 `docker compose restart app`。要重新初始化样例数据，先备份所需记录，再执行 `docker compose down -v` 与 `docker compose up --build -d`；此操作会删除当前项目的历史与复核数据。

## 定义与边界
原始行=采信事件+无效曝光+重复回调+其他隔离+空行。原始费用-合法扣减=应付。CPM单位为CNY/千次，先按渠道和北京时间账日求和，再HALF_UP舍入到分。扣减额采用原始舍入总额与净额之差，保证分币守恒。机器事件优先于频次，机器事件不消耗频次；频次按渠道、账日、用户计数。冲销事件本身不计曝光，不占频次，须不早于原事件且渠道相同。ID保留为字符串。

## 已知不覆盖
本地样例资费按月固定，不实现实时竞价和竞价超时。冲销只处理整次曝光，不支持部分曝光冲销。重复冲销与对未采信曝光的冲销进入隔离，不能由人工直接改为计费。

## 目录
`app/modules/` 为七个业务模块，`sample_data/` 提供基准与异常台账，`tests/` 包含模块测试与端到端测试，`docs/` 保存定义与深度登记。
