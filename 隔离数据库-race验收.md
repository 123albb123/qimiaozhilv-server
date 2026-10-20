# 隔离数据库与live条件下的race补跑

检测日期：2026-10-20；整理与环境清理：2026-10-21。状态：**57项全部实际通过，根包854项通过、0失败、0跳过，未检测到数据竞争**。

## 范围与环境

历史根包race记录有797项通过、57项因数据库/live条件不足跳过。本次以 `server-mysql/test/race_mysql_required.txt` 固定这57项名称，要求每项真实执行并通过。
从整个根包开始运行，包含交易、背包、奖励、任务、家族、排行榜、装备迁移及存档重开等现有回归。

- 执行平台：Windows amd64，Go1.25.0、MinGW GCC、CGO_ENABLED=1。
- 测试程序和独立测试游戏服均由 `go version -m` 核对 `-race=true`；不是仅给HTTP探针加race，也不是NAS Linux平台race验证。
- 新建MySQL8.0.37与Redis7.4临时容器，使用本次独立随机密码；MySQL数据仅写入 `/vol1/1000/docker/qimiao/isolated/race-direct-20261020/mysql`。
- 临时数据库端口13360、Redis端口16380；独立测试游戏服只监听本机127.0.0.1:7756。正式游戏仍在NAS7756，两者没有连接或数据目录复用。
- 隔离库 `mhq_race_live` 从生成的YAML配置原子初始化79份配置。数据库单测在同一临时MySQL实例创建、清理各自的 `mhq_test_*` 夹具库；live金币测试也只连接临时实例和临时Redis。
- 正式四容器未停止、重建或部署新程序；测试运行期间核对原12个容器ID保持不变，正式四服务健康。

原Docker socket辅助容器方案被自动审批拒绝，未启动。实际执行改为fnOS直接创建两个临时数据库容器、本机运行race，不挂载Docker socket。未执行的NAS辅助脚本已删除。

## 实际发现与修复

首次测试启动因PowerShell原生命令参数未加引号而失败；失败记录脱敏单独保留。修正参数后执行的首轮整包到343项通过、7项原缺测通过时，检测到一处DATA RACE并按设置停止。

堆栈：延迟回城的 `finishMapStartupWithOptions → pushUnitResourceAttrs → equipBonus` 读取 `tables`，与后续 `TestLegacyShoeMigrationAlignsWireAndStamina` 清理时恢复全局配置竞争。原因为个人竞技/组队顶号测试结束后，异步地图回调没有随夹具结束失效；连接真实MySQL后测试间隔变长，暴露了遗留回调。

提交 `694f4c6` 在 `dungeonTeamTestParty`、个人竞技匹配用例和组队顶号用例补充现有 `cleanupGameTestServer`。它失效夹具会话并等待正在执行的地图回调，先于还原共享配置执行；没有修改生产游戏规则或Go业务代码，也没有用Sleep掩盖竞争。

相关4个测试在隔离MySQL下以 `-race -count=3` 连续复验通过，49.053秒：

- `TestPersonalPVPLeavesTeamsOnlyAfterMatch`
- `TestReplaceDuringPartyActivityCleansClientsBeforeRemovingUnit`
- `TestLegacyShoeMigrationAlignsWireAndStamina`
- `TestLegacyEquipmentAttributeMigrationMySQL`

随后重新编译测试程序，从头重跑整个根包。先前失败日志保留，不与修后结果拼成单次通过。

## 结果与证据

最终修后整包于2026-10-20 23:34:07开始，23:54:29结束（Asia/Shanghai），耗时1222.157秒（20分22秒），进程退出码0。

| 检查 | 最终结果 |
| --- | --- |
| 原先跳过的57项 | 57/57实际PASS，无缺测 |
| 整个根包 | 854 PASS，0 FAIL，0 SKIP |
| race报告 | 测试程序与独立测试游戏服日志均无DATA RACE |
| 重点链路 | 整包包含交易、背包操作、奖励防重复及跨数据库重开存档用例，全部PASS |
| 正式服务 | 原12个容器ID保持，项目4个服务健康；未部署或修改正式游戏/数据库 |
| 测试环境清理 | 两个临时数据库容器和13360/16380端口已删除；本机测试游戏服已退出，独立测试数据和日志保留 |

本次只使用已有MySQL/Redis镜像，没有构建新测试镜像。测试过程中唯一代码修复为上述测试夹具清理；正式业务Go代码及运行镜像未变。

测试二进制SHA256：`a2d949c1aac01f248e15a60a5088d551a52afe354f776d1a37cf7f7663b8337d`。
独立race游戏二进制SHA256：`9ffeb7c7896c1e82e20c766fc19de6de535a9e6a9da8e3ed8011519e07721ed3`。
原始事件SHA256：`eeb69bde628b7cada95b6f206f66af3e923cd5e7ea15eff63632e5fd8baf8030`。
独立游戏日志SHA256：`e74cc423bf83e8e09da8c3a9edb0158dbf593c1a8a13d28f9a3b33fb3668ffd0`。

### 57项逐项结果

| 测试 | 结果 |
| --- | --- |
| `TestAccountAndPlayerNameUniqueness` | PASS |
| `TestConfigFileMatchesPublishedDetectsValueChange` | PASS |
| `TestDailyDungeonQuotasSurviveDatabaseReopen` | PASS |
| `TestDeletePlayerRelationsRemovesGhostReferences` | PASS |
| `TestDetachLastMemberDissolvesFamily` | PASS |
| `TestDetachPlayerFromFamilyPromotesRemainingMember` | PASS |
| `TestDissolveFamilyClearsDanglingMembers` | PASS |
| `TestFamilyApplicantCanJoinAfterLeaderApproval` | PASS |
| `TestFamilyApprovalClearsRequestsToOtherFamilies` | PASS |
| `TestFamilyApprovalRemovesOrphanedRequest` | PASS |
| `TestFamilyBossDailyRefreshSurvivesRestart` | PASS |
| `TestFamilyBossDamageSurvivesDatabaseReopen` | PASS |
| `TestFamilyBossLegacyDeadRowStampsTimeInsteadOfRevivingImmediately` | PASS |
| `TestFamilyBossProgressSurvivesDatabaseReopen` | PASS |
| `TestFamilyBossRewardClaimSurvivesDatabaseReopen` | PASS |
| `TestGMCurrencyGoldUnitLive` | PASS |
| `TestGMFamilyResetClearsStaleSessionOverCleanDatabase` | PASS |
| `TestGMFamilyResetDetachDissolvesLastMember` | PASS |
| `TestGMFamilyResetDetachPromotesRemainingMember` | PASS |
| `TestGMFamilyResetDissolveClearsEveryMember` | PASS |
| `TestGMFamilyResetDissolveWithoutFamily` | PASS |
| `TestGMFamilyResetRejectsUnknownMode` | PASS |
| `TestGMFamilyResetRejectsUnknownPlayer` | PASS |
| `TestGMFamilyResetWithoutFamilyIsIdempotent` | PASS |
| `TestGMFamilyResetWorksOffline` | PASS |
| `TestHealDanglingFamilyRefAllowsCreate` | PASS |
| `TestHealDanglingFamilyRefAllowsJoin` | PASS |
| `TestHealDanglingFamilyRefIsIdempotent` | PASS |
| `TestHealDanglingFamilyRefOnGetFamily` | PASS |
| `TestHealLeavesHealthyFamilyAlone` | PASS |
| `TestInitialConfigSyncMatchesRealOperationFile` | PASS |
| `TestInitialConfigSyncPublishesInvalidFileSoTheErrorIsLoud` | PASS |
| `TestInitialConfigSyncPublishesOnlyWhenContentDiffers` | PASS |
| `TestInitialScanAlignsFilesChangedWhileServerWasDown` | PASS |
| `TestItemBuffAddReplaceRestoreAndPersist` | PASS |
| `TestItemPurchaseOriginMySQLRoundTrip` | PASS |
| `TestLargeRankingSnapshotMatchesFullRelations` | PASS |
| `TestLauncherTeamPlanRejectsWrongPassword` | PASS |
| `TestLegacyEquipmentAttributeMigrationMySQL` | PASS |
| `TestLoginCredentialsRemainStrictAcrossRoleDeletion` | PASS |
| `TestNewRoleKeepsReservedIdentityThroughFirstEntry` | PASS |
| `TestNewRoleVoucherFollowsGameplayConfig` | PASS |
| `TestPVPRequestAndBoardState` | PASS |
| `TestPlayerCurrentResourcesPersistAcrossDatabaseReopen` | PASS |
| `TestPlayerEnergyDefaultsAndPersists` | PASS |
| `TestPlayerIDReservationPersistsAndDrivesRoleCreation` | PASS |
| `TestPlayerProgressSurvivesDatabaseReopen` | PASS |
| `TestQuizScoreBoardUsesLightweightSortedSnapshot` | PASS |
| `TestRankingOrdersDescendingAndBreaksTiesByPlayerID` | PASS |
| `TestReadPublishedConfigRoundTripsDatatableRoot` | PASS |
| `TestReadPublishedConfigRoundTripsMapRoot` | PASS |
| `TestRejectedRegistrationDoesNotCreateAccount` | PASS |
| `TestSigninPersistsThroughMySQLReload` | PASS |
| `TestStoreConcurrentAccountCreationDoesNotReturnBusy` | PASS |
| `TestStoreSortAndExpandPersist` | PASS |
| `TestTaskProgressTypesAndPersistence` | PASS |
| `TestTransferJobPersistsProfessionAndLearnedBaseSkill` | PASS |

私有原始事件、退出码、游戏日志、初次失败及定向复验日志在本机 `F:\codex\qimiao\task-records/`，不提交玩家数据、凭据或大体积原始日志。
`summarize_isolated_race.py` 要求根包正常结束、退出码0、无失败或跳过、57项逐一PASS，且测试和游戏日志均无DATA RACE。它已经用真实失败记录验证会拒绝1处race与50项尚未执行的情况。

复跑环境、编译和严格汇总命令见 `server-mysql/test/README.md`。这份Go并发检测报告与《客户端验收-qimiaozhilv.md》的用户手测、原生界面覆盖范围分别记录；race通过不能代替尚未覆盖的Unity玩法验收。
