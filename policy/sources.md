# 政策调研笔记（sources）

所有条目**访问日期 2026-09-28，2026-10-09 在浏览器中逐条复核**：全部链接可打开，每段摘录在原文中逐句核对一致；复核时发现的更新（A15 文章日期、B7 指南版本、B1 版本日期）已就地注明。Ryde 帮助中心 (help.rydesharing.com) 页面对普通抓取返回 403，原文均通过 Zendesk 公开 JSON API（`https://help.rydesharing.com/api/v2/help_center/en-us/articles/<id>.json`，搜索 `…/articles/search.json?query=`）取得，"更新"为文章 `updated_at`；Grab 帮助中心需 JS 渲染无法抓取，Grab 数据来自其政策页与行为准则页。**摘录均为原文（英文），不转述**；`policy/policy.md` 的条款以本文件编号（A7、B1 …）引用。

分类：**A** Ryde 一手；**B** 新加坡法规 / LTA / PTC / 法院；**C** 新加坡其他运营商；**D** 国际参照与技术文档；**E** 本系统设计文档。

## A. Ryde 官方（一手）

### A1. Cancellation and Waiting Fee（乘客侧政策声明）
- URL：https://help.rydesharing.com/hc/en-us/articles/23534478435353-Cancellation-and-Waiting-Fee （id 23534478435353，更新 2026-02-26，访问 2026-09-28）
- 摘录："All cancellations made within 3 minutes of matching are not chargeable. Rider will be charged a Cancellation Fee of $6.61* if: Rider cancels after 3 minutes of matching OR The driver presses "I'm Here", waits for > 3 minutes for the rider to arrive at the pick-up point and cancels the trip (Rider NO SHOW and no trip completion) Riders may be charged a Waiting Time Fee of $5 at the end of the trip if: The driver presses "I'm Here", waits for > 3 minutes for the rider to board, and continues the trip"
- 预约单："All cancellations made > 15 minutes before the scheduled trip time are not chargeable … If the advanced trip request is accepted only after 5:45 PM, riders will have a 3 minute grace period."
- 采用：NS-0 / NS-1 / NS-2 / NS-4 / NS-5 / NS-6 的金额（$6.61、$5）和时间阈值（3 min、15 min）；RD-3(c)（Ryde 只公布上车点等待费）。

### A2. Cancellation and Waiting Time Policy（司机侧）
- URL：https://help.rydesharing.com/hc/en-us/articles/20244064619161-Cancellation-and-Waiting-Time-Policy （id 20244064619161，更新 2024-12-19，访问 2026-09-28）
- 摘录："Driver will receive a Cancellation Fee of $4.50* if: Rider cancels after 3 minutes of matching. Driver may charge a Waiting Time Fee of $4.50 at the end of the trip if: The driver pressed 'I'm Here', waits for > 3 minutes …"
- 采用：NS-1 "$4.50 归司机"；NS-4。

### A3. What if my driver hasn't arrived, but has indicated that he/she arrived?
- URL：https://help.rydesharing.com/hc/en-us/articles/4407754403353 （id 4407754403353，更新 2026-02-26，访问 2026-09-28）
- 摘录："Drivers are only allowed to indicate arrival and impose the Waiting Time Fee only if he/she: Is at the pick-up location according to GPS data AND Has waited for more than 3 mins Otherwise, you will not be charged the $6.61 Waiting Time Fee if any of the above are not fulfilled."
- 采用：NS-1 / NS-2 / NS-6 的"GPS 位于上车点 + > 3 min"两要件；法官"系统记录优先于口供"的程序规则（代码）。注意原文把 $6.61 写成 "Waiting Time Fee"，与 A1 的 $5 等待费不一致，应为笔误（$6.61 是取消费）。
- **未公开**：GPS "at the pick-up location" 的半径（帮助中心搜索 "radius" 0 结果，"GPS" 仅此一篇）。→ 空缺 G2。

### A4. Cancellation Fee Waiver Request / Waiting Fee Waiver Request
- URL：https://help.rydesharing.com/hc/en-us/articles/18229758389017 ；https://help.rydesharing.com/hc/en-us/articles/27085468660505 （均更新 2026-09-25，访问 2026-09-28）
- 摘录："you may submit a fee waiver request via RydeHELP in our app within 30 days of the trip* and we will review your eligibility for a refund." / "we will issue you a voucher with a unique code worth $6.61 [/ $5.00] as a refund … This voucher is non-refundable and cannot be exchanged for cash … The increase is due to the platform fee changes effective 17 Feb 2026."
- 采用：NS-7（30 天、代金券）。

### A5. How Does the Cancellation Fee Work? / How Does the Waiting Fee Work? / What if I forgot to add in the Waiting Time Fee?
- URL：https://help.rydesharing.com/hc/en-us/articles/4408070838297 ；…/4408071347993 ；…/4408079464217 （均更新 2026-09-25，访问 2026-09-28）
- 摘录："Drivers will receive a $4.50 cancellation fee automatically if they cancel after >3 minutes of waiting." / "Drivers are required to tap on the $5* Waiting Time Fee button upon Drop-off." / "we are unable to charge the rider once the trip is completed."
- 采用：NS-1（$4.50）、NS-6（等待费须在行程内按钮触发）。

### A6. Service Fee / Platform Fee
- URL：https://help.rydesharing.com/hc/en-us/articles/360003567993-Service-Fee （更新 2026-02-16，访问 2026-09-28）；https://help.rydesharing.com/hc/en-us/articles/22836370596377-Platform-Fee
- 摘录："First Tier Platform Fee: $1.25 (including GST) for fares $18 and below. Second Tier Platform Fee: $1.47 (including GST) for fares above $18."
- 采用：FARE-1 的"已公布附加费"；`data/rates.json` 平台费两档。（旧版笔记中的 "$6.61 = $4.50 + 平台费 + 交易费" 分解已删除：算不平，Ryde 未公布分解。）

### A7. Am I required to follow the suggested route by the rider? / Can I suggest my preferred route to the driver?
- URL：https://help.rydesharing.com/hc/en-us/articles/4412122016153 （更新 2023-07-15）；https://help.rydesharing.com/hc/en-us/articles/4412121982745 （更新 2024-10-01）（访问 2026-09-28）
- 摘录："The trip fare is fixed based on pick-up and drop-off points. So you may decide to take the fastest or most efficient route based on your GPS." / "The trip fare is fixed based on pick-up and drop-off points, hence the driver may decide to take the most efficient route according to GPS. If you have a preferred route, you may recommend this to your driver and reach a mutual agreement before you go."
- 采用：第 0 节车费模型；RD-1 / RD-4 的"最优路线"基准；RD-5 的"事前双方同意"。
- **未公开**：绕路阈值、绕路退款计算。帮助中心搜索 longer route / detour / fare review / overcharged / fare adjustment / refund / estimate 均无绕路退款文章。→ 空缺 G1、G5。

### A8. I was overcharged for ERP/toll / Are surcharges included in the base fee?
- URL：https://help.rydesharing.com/hc/en-us/articles/30741244296217 （更新 2025-11-23）；…/4408072421785 （更新 2025-11-23）（访问 2026-09-28）
- 摘录："Fares quoted for our services are generally fixed, except for RydeTAXI. However, please note that there may be additional charges such as tolls that could occur during your trip." / "Surcharges such as toll charges, overtime fees and valet parking fees are excluded from the base fare. You will be charged for such additional fees at the end of the trip."
- 采用：第 0 节；FARE-1 / FARE-2；RD-2 非计价器分支。

### A9. Edit destination fee / Can I change my destination? / Add a stop
- URL：https://help.rydesharing.com/hc/en-us/articles/51399796192921 ；…/51400229761177 （均更新 2025-10-10）；…/50798691815449 （更新 2026-09-25）；…/34883561600025 （更新 2026-09-25）（访问 2026-09-28）
- 摘录："Yes. If the driver accepts your edit destination request, a $3.00 add/edit destination fee will apply. This fee will be reflected in your receipt once the trip is completed." / "The driver can accept or reject the request. If the driver rejects, the previous trip details remain, and no fee is reflected." / "Fare Adjustment – Once the driver accepts, your trip fare will be recalculated, and your route will be updated to the new destination. *RydePOOL, RydeTAXI & Multiple stop bookings are not allowed to make any changes in destination. Effective 17 Oct 2025" / "Your rider won't be able to request the change of drop-off location and/or add an additional stop for: Multiple stop requests RydePOOL booking RydeTAXI booking"
- 采用：RD-3(c)、FARE-1。

### A10. Driver Performance and Community Standards
- URL：https://help.rydesharing.com/hc/en-us/articles/33362721809049 （id 33362721809049，更新 2026-04-10，访问 2026-09-28；早期笔记引用的 id 20244107265689 为同名文章，2026-09-28 审核时亦已核实）
- 摘录："Conditions, where driver accounts will be temporarily disabled: Driver Rating (DR) < 4.80 Cancellation Rate (CR) > 17.5% … Fraudulent Activity Drivers who overcharge riders and/or complete the trip without the rider onboard." / "Drivers who are found to have overcharged riders or completed trips without the rider onboard may face account suspension. The Ryde Driver app is equipped with Artificial Intelligence (AI) algorithms that automatically detect and flag suspicious activity." / "Fraudulent behavior may take many forms. This includes, but is not limited to: 1. Overcharging riders or manipulating fares 2. Completing trips without the rider onboard … 5. Remaining stationary and uncontactable after accepting a ride to trigger cancellation or waiting fees … 8. Abuse of Cancellation and Waiting Fee Policy" / "Where Ryde reasonably suspects serious or repeated violations, it may report such conduct to government agencies such as … Land Transport Authority (LTA)" / "Driver-partners will be given the opportunity to respond before final decisions are made, except in urgent or high-risk situations. Repeated or severe breaches may lead to permanent suspension from the Ryde platform." / "Repeated failure to abide by Ryde community standards will lead to permanent suspension from the Ryde platform." / "The driver's rating is calculated based on his/her last 100 trips"
- 采用：RD-2 / RD-6（overcharge、repeated）、NS-2 `flag_account`（第 5、8 项）、NS-3（CR > 17.5%）、SAFE-3。
- **未公开**："repeated" 的次数与时间窗。→ 空缺 G4。

### A11. I received an SMS or Email regarding irregular trip behaviour
- URL：https://help.rydesharing.com/hc/en-us/articles/6959605073177 （更新 2023-06-08，访问 2026-09-28）
- 摘录："This SMS is sent to drivers who accounts have been flagged by our algorithm. … Driver actions: Multiple cancellations Low driver ratings Overcharging of additional fees Abuse of the cancellation and waiting time button Trip characteristics: Trips that were completed without rider onboard Unusual trip patterns Speeding and reckless driving"
- 采用：RD-2、RD-6、NS-2、SAFE-3 的 `flag_account` 依据。

### A12. I completed a trip without picking up the rider
- URL：https://help.rydesharing.com/hc/en-us/articles/20692560042649 （更新 2024-06-06，访问 2026-09-28）
- 摘录："You will not be able to cancel the trip once you tap 'Pick Up'. If your rider has been charged for a trip that you could not cancel, please let us know."
- 采用：SAFE-3。

### A13. Ryde Code Of Conduct
- URL：https://help.rydesharing.com/hc/en-us/articles/15395890865561 （更新 2026-06-15，访问 2026-09-28）
- 摘录："Assault, harassment, or abuse of any kind will not be tolerated … This includes … Threats and Intimidation, Unwanted Sexual Advances … In any dispute, drivers must not take matters into their own hands but follow the appropriate reporting procedures. Violations of these guidelines will result in immediate termination and legal action where applicable." / "Refusing or cancelling a trip without a valid reason at pick-up may result in account action."
- 采用：SAFE-1（类别）、NS-3；法庭安全筛查（SAFE-1）所用类别的依据。

### A14. Report a safety issue / I was involved in an accident / feedback about my driver
- URL：https://help.rydesharing.com/hc/en-us/articles/51354502165913 ；…/900003838306 ；…/18230876398105 （均更新 2026-09-25，访问 2026-09-28）
- 摘录："If you're in need of medical assistance, please call 995 … You may file a medical claim through your driver's commercial motor insurance. Report to us swiftly via RydeHELP." / "Our system automatically suspends drivers/riders who fall below a certain threshold. In the worst scenarios, drivers will be permanently banned."
- 采用：SAFE-2。

### A15. My Rider Made a Mess（清洁费）
- URL：https://help.rydesharing.com/hc/en-us/articles/900004381243 （更新 2026-10-09；2026-09-28 访问时为 2026-09-25 版，2026-10-09 复核摘录内容未变）
- 摘录："Your vehicle must be professionally cleaned within 24 hours from the incident. Submit your claim via the driver app within 48 hours … At least one photo must show the vehicle's car plate number … Spillage of food/drinks … Up to $40; Human or pet bodily fluids … Stains … Up to S$120; Vomit Up to S$200 … You can appeal within 24 hours."
- 采用：FARE-3（信息性）。

### A16. Terms of Use
- URL：https://rydesharing.com/terms-of-use/ （访问 2026-09-28，curl 抓取）
- 摘录："If you decide to cancel your ride booking or do not show up at the designated location, you may be charged a Cancellation Fee or such other Cancellation Fee as Ryde may notify from time to time via the Cancellation and Waiting Time Policy on Ryde's website. If you feel you were incorrectly charged a Cancellation Fee, you may contact Ryde in writing at [email protected] for assistance. Ryde reserves its absolute discretion to any refunds to you and such refunds may be credited to the payment card you used for the journey, or to your RydeCoins wallet or by such other method as is deemed reasonable by Ryde." / "Cancellation Terms for Partners … the cancellation shall be based on acceptable cancellation reasons as shown in the Application." / "Complaints Any complaints between Partners and Users must be taken up with each other directly." / "Ryde will not be a party to disputes or negotiations of disputes between you and Users or Partners" / "Riders may be subject to a cleaning fee of up to S$200 for incidents requiring professional cleaning." / "You agree to assist Ryde with any internal or external investigations as may be required by Ryde in complying with any prevailing laws or regulations in place;" / "Dispute Resolution These Terms of Service shall be governed by Singapore law … Any disputes … shall be referred to the Singapore International Arbitration Centre ("SIAC")"
- 采用：NS-0、NS-3、NS-7（Ryde 保留退款裁量权）、FARE-3 上限。
- **未公开**：ToU 无绕路、车费复核、退款时限条款；"conclusive evidence" 措辞只用于 RydeCoins 余额（"The RydeCoins balance set out in the Application shall serve as conclusive evidence of the amount of your RydeCoins."），没有行程/GPS 记录为准的条款；另有免责 "Ryde does not warrant or represent that it assesses or monitors the suitability, legality, ability, movement or location of any Users or Partners"。

### A17. Ratings and Reviews Moderation Policy
- URL：https://help.rydesharing.com/hc/en-us/articles/20244161586585 （更新 2024-12-19，访问 2026-09-28）
- 摘录：评价须 "relevant to the rider's Point-to-Point transport experience"；与 "Mapping / GPS / Product / Technical Issues" 等司机无法控制的因素相关的评价会被移除。
- 采用：法官程序规则"画像不单独定案"（代码）的旁证。

### A18. 其他确认过的 Ryde 事实
- 取消政策适用范围：https://help.rydesharing.com/hc/en-us/articles/4407761313305 （更新 2025-11-23，访问 2026-09-28）全文："Cancellation Policy applies to all Service Types * in the Ryde app and is executed on a service level, not driver level. Hence, all carpool drivers are included in the Cancellation Policy. *All services except RydeTAXI" → NS-0。
- RydeTAXI 计价器：https://help.rydesharing.com/hc/en-us/articles/900004230226 （更新 2026-01-26）"Do note that all fees for Standard and/or Premium taxis follow that of the respective taxi company. Key in the fare as indicated on your meter. Please do note that the payment method accepted for RydeTAXI is only via cash ." → 第 0 节、RD-3(c)。
- 司机侧里程计费说明：https://help.rydesharing.com/hc/en-us/articles/52948811893145 （"Pickup Distance Upgraded"，更新 2025-12-02）"Fares are calculated from actual driven distance and time, so you are always paid correctly for the route you take." / "GPS or map glitches may happen occasionally. Simply report it to support via Rydehelp so we can improve accuracy."
- 司机不允许使用行车记录仪/IVRD（https://help.rydesharing.com/hc/en-us/articles/51812996696217 ，2025-10-24）→ 安全事件证据只能来自聊天、GPS、报告。
- 司机联系不上乘客时可取消，CR 已为 no-show 留缓冲（https://help.rydesharing.com/hc/en-us/articles/115001438754）。
- **未找到**：行程中停靠 / 等待如何收费（搜索 stop / multiple stops / waiting during trip 无结果）→ 空缺 G6。

## B. 新加坡法规、LTA / PTC、法院

### B1. Road Traffic (Public Service Vehicles) (Vocational Licences and Conduct of Drivers, Conductors, Trishaw Riders and Passengers) Rules
- URL：https://sso.agc.gov.sg/SL/RTA1961-R8 （页面显示 "Current version as at <访问当日>"，访问 2026-09-28，2026-10-09 复核 r.23 与 r.25 原文未变）
- 摘录："Conduct of taxi drivers 23. —(1) A licensee, when acting as a taxi driver, shall — … ( c ) in the absence of any reasonable cause to do otherwise, proceed to the destination named by a passenger or hirer of the taxi by the shortest and most direct route; ( d ) start the taximeter fitted to the taxi only after the passenger has, or if there is more than one passenger, all of the passengers have, boarded the taxi and the licensee has accepted the hiring of the taxi; ( da ) stop the taximeter as soon as the hiring of the taxi is terminated;" / "Prohibition on refusal to convey passenger 25. No taxi driver shall, without reasonable excuse, refuse to hire out his taxi or convey any passenger for the purpose of gain."
- 说明：r.23 适用于出租车司机（RydeTAXI 案 C-0001/2/3 均为出租车）；原多收费用款 23(1)(l) "[Deleted by S 919/2020 wef 30/10/2020]"，多收费用现由 Point-to-Point Passenger Transport Industry Act s.23 规制（见 B2）。
- 采用：RD-1、RD-3、RD-4（"reasonable cause"）、NS-3。

### B2. Road Traffic (Chauffeured Private Hire Car and Taxi Vocational Licence Demerit Points System) Rules 2017，First Schedule
- URL：https://www.lta.gov.sg/content/dam/ltagov/industry_innovations/industry_matters/regulations_licensing/taxis_private_hire_cars/private_hire_car_licence/pdf/Road%20Traffic%20(Chauffeured%20Private%20Hire%20Car%20and%20Taxi%20Vocational%20Licence%20Demerit%20Points%20System)%20Rules%20wef%2030%20Oct%202020.pdf （S 365/2017，"Informal Consolidation – version in force from 30/10/2020"，访问 2026-09-28）
- 摘录（Offence | provision | points）："10. Refusing, without reasonable excuse, to hire out taxi or to convey passenger | Rule 25 PSVC | 6" / "14A. Demanding from taxi passenger street-hail fare inconsistent with any part of street-hail fare pricing policy for street-hail service | Section 23(2)(a) read with section 23(4) PTCA | 3" / "14B. Demanding from taxi passenger street-hail fare more than streethail fare last published by streethail service licensee for streethail service | Section 23(2)(b) read with section 23(4) PTCA | 3" / "16. Failing, without reasonable cause, to proceed to destination named by a passenger by shortest and most direct route | Rule 23(1)(c) PSVC | 3" / "17. Starting taximeter before boarding of passenger or passengers, and hiring of taxi | Rule 23(1)(d) PSVC | 3"
- 采用：RD-1、RD-6、NS-3。

### B3. LTA — PDVL / TDVL holders offences（罚款与扣分对照）
- URL：https://www.lta.gov.sg/content/dam/ltagov/industry_innovations/industry_matters/regulations_licensing/taxis_private_hire_cars/private_hire_car_licence/pdf/PDVL_holders_Offences.pdf （"accurate as at 1st Apr 2023"，访问 2026-09-28）
- 摘录："23 Refusing, without reasonable excuse, to hire out taxi or convey passenger Rule 25 PSVC $300 6" / "25 Failing, without reasonable cause, to proceed to destination named by a passenger by shortest and most direct route Rule 23(1)(c) PSVC $100 3"
- 采用：RD-1、RD-6 背景。

### B4. LTA 新闻稿：Enforcement action against errant taxi drivers（2023-12）
- URL：https://www.lta.gov.sg/content/ltagov/en/newsroom/2023/12/news-releases/enforcement_action_against_errant_taxi_drivers.html （访问 2026-09-28）
- 摘录："Collected a fare that is less than $20 above the metered fare $500 12 Collected a fare that is $20 or more above the metered fare $500 21" / "Under LTA's Vocational Licence Demerit Points System, an accumulation of 6 demerit points or more would result in the suspension of the vocational licence, while 21 demerit points or more would result in the revocation of the vocational licence."
- 采用：RD-2（超出应付计价器车费的部分不属司机应得）、RD-6。

### B5. LTA — Taxi Fares & Payment Methods
- URL：https://www.lta.gov.sg/content/ltagov/en/getting_around/point_to_point_transport_and_cross_border_services/taxi_fares_payment_methods.html （访问 2026-09-28）
- 摘录："Standard 26 cents every 400m (1km – 10km) 26 cents every 350m (above 10km) 26 cents for every 45 sec of waiting time Premium 37 to 38 cents every 400m (1km – 10km) 37 to 38 cents every 350m (above 10km) 37 to 38 cents for every 45 sec of waiting time" / "Peak Periods … 25% of metered fare Late Night Hiring Every day from midnight to 5.59am 50% of metered fare"
- **未找到**：等待时间计费的速度条件（"低于 X km/h"）在 LTA/PTC 页面无原文；坊间指南称约 20 km/h，不采用。
- 采用：第 0 节、RD-2（里程单位）、RD-3(c)（等待单位）、空缺 G10。

### B6. PTC — Point-to-point transport fares
- URL：https://www.ptc.gov.sg/fares/point-to-point-transport-fares/ （访问 2026-09-28）
- 摘录："Ride-hail operators are required to state flat fare clearly to commuters at the point of booking; and Ride-hail operators are also required to publish any additional fees and charges that may be levied." / "All ride-hail flat fares will be dynamically determined by operators. However, this amount must be provided upfront to the commuter prior to the booking. Any additional fees and charges may be charged over the initial flat fares that was provided upfront to the commuter, e.g. additional stop charge, waiting time charge and other fees must be published." / "Ride-hailed taxi metered fares must follow the metered fare structure and amounts of the taxi company who owns that taxi."
- 采用：第 0 节、FARE-1、RD-3(c)（非计价器行程中等待费须公布，Ryde 未公布 → 不可收）。
- **未找到**：PTC / LTA 关于投诉处理、GPS 记录、"到达"定义的行业准则。

### B7. LTA DataMall API User Guide & Documentation v6.10（1 Oct 2026；2026-09-28 访问时为 v6.9，3 Aug 2026）
- URL：https://datamall.lta.gov.sg/content/dam/datamall/datasets/LTA_DataMall_API_User_Guide.pdf （访问 2026-09-28）
- 摘录（Traffic Speed Bands，`/ltaodataservice/v4/TrafficSpeedBands`，"Returns current traffic speeds on expressways and arterial roads, expressed in speed bands." "Update Freq 5 minutes"）："RoadCategory 1 – Expressways 2 – Major Arterial Roads 3 – Arterial Roads 4 – Minor Arterial Roads 5 – Small Roads 6 – Slip Roads 8 – Short Tunnels" / "SpeedBand Speed Bands Information. Total: 8 1 – indicates speed range from 0 < 9 2 – indicates speed range from 10 < 19 3 – indicates speed range from 20 < 29 4 – indicates speed range from 30 < 39 5 – indicates speed range from 40 < 49 6 – indicates speed range from 50 < 59 7 – indicates speed range from 60 < 69 8 – speed range from 70 or more"
- 说明：Traffic Incidents 数据集字段 `Type, Latitude, Longitude, Message`，Type 含 Accident / Roadwork / Vehicle breakdown / Weather / Obstacle / Road Block / Heavy Traffic 等（§2.18，v6.9 与 v6.10 相同）。OneMotoring traffic.smart 图例只有 "Slow" / "Fast"，无 km/h 门槛。
- 采用：RD-4、路况匹配半径（数据层参数）、字段映射、`road_category` 数字编码。→ 空缺 G3（"拥堵"无官方定义）。

### B8. Small Claims Tribunals — cases eligible
- URL：https://www.judiciary.gov.sg/civil/cases-eligible-small-claim （访问 2026-09-28）
- 摘录："You can file if your claim... Has a total value of up to $20,000 (or $30,000 if there is a Memorandum of Consent from both parties). Is filed within 2 years of the event which creates your cause of action . Involves any of the following: A contract for the sale of goods . A contract for the provision of services . ... A dispute against a supplier for an unfair practice under the Consumer Protection (Fair Trading) Act."
- 采用：NS-7 背景（系统裁决为建议，乘客保留法定救济）。CASE 无网约车专项指引。

## C. 新加坡其他运营商（派生依据）

### C1. Grab Singapore — Cancellation Policy for a Fairer Platform（Effective 18 July 2022）
- URL：https://www.grab.com/sg/cancellationpolicy/ （访问 2026-09-28）
- 摘录："For rides other than GrabHitch, if you're made to wait for more than 5 minutes after the indicated ETA, you'll be allowed to cancel your ride with no fee. Conversely, if you cancel after 3 minutes, your driver will receive a $4 compensation from you to make up for the time, petrol, and effort he took getting to you." / "You will only incur a cancellation fee when the driver cancels the booking after waiting 5 minutes at your pick-up point." / "Just as we're able to show you your driver's current location, we have safeguards in place to detect if the driver's not moving towards you. Cancellation fees are waived if your driver does not arrive within 3 minutes after the first-shown estimated time of arrival." / "Drivers are only allowed to cancel the ride and impose the cancellation fee only if he/she: Is at the pick-up location according to GPS data Has waited more than 5 mins You will not be charged the $4 cancellation fee if any of the above are not fulfilled."
- 采用：NS-2 同构佐证；NS-8（信息性）。无米数。

### C2. Grab SG — Code of Conduct – Driver / Delivery Partner Penalty Guidelines
- URL：https://www.grab.com/sg/terms-policies/code-of-conduct-driver/ （访问 2026-09-28）
- 摘录："Discuss and agree with the user before taking an alternative route or ensure that the shortest and most direct route is taken." / "Agree with your passenger on the route to take , or ensure that you take the shortest and most direct route ." / Examples of Infringement: "Changing route without passenger's permission" / "Overcharging by collecting a higher fare than that stated on the app or meter, entering a wrong surcharge, or charging fares which are not in accordance with the rates in the Grab app or published on Grab's website" / "Cancelling a booking without a valid reason or giving a false reason" / "Wait for your user for a reasonable amount of time."
- 采用：RD-1、RD-3、RD-5。

### C3. Gojek Singapore — Updated: cancellation and waiting fees（2022-09-26 起）
- URL：https://www.gojek.com/sg/blog/news-cancellation-waiting-fee-gojek-singapore-2022 （访问 2026-09-28）
- 摘录："You will be charged a $4 fee if you cancel: After 4 minutes from when you've been matched to a driver or As soon as your driver arrives at your pick-up location, or If your driver cancels after arriving and waiting for more than 4 minutes" / "You will not be charged if you cancel: Within 4 minutes from getting matched to a driver, as long as the driver hasn't arrived or If more than 5 minutes has passed from the initial indicated ETA, and the driver hasn't arrived at the location" / "Our app is also able to detect if the driver is not moving towards you." / "There are no waiting fees for GoTaxi – the meter will run according to the fares allocated."
- 采用：NS-8（信息性）；RD-3(c)（出租车按计价器）。Gojek 帮助中心 fares 页 HTTP 500，无绕路条款。

### C4. CDG Zig — Help Centre："Can I choose my preferred route during my ride?"
- URL：https://zig.live/help-center/ （访问 2026-09-28）
- 摘录："For Flat Fare bookings, drivers are entitled to choose the quickest or most direct route as suggested by GPS navigation. For Metered Fare bookings, passengers have the option to select the route upon boarding the taxi. In the absence of specific instructions from the customer, the driver is obligated to follow the most direct route to fulfill the journey, in accordance with the Road Traffic Act."
- 采用：RD-1、RD-3。

### C5. ComfortDelGro Taxi — Cancellation Policy 2025
- URL：https://www.cdgtaxi.com.sg/cancellation-policy-2025/ （访问 2026-09-28）
- 摘录："Last-Minute Cancellation : You cancel the ride after your driver has arrived at your pick-up point. No-Show : Your driver arrives and waits for you, but you do not appear within the standard grace waiting period." / "Cancellation Fee (after arrival) : From $4.00 No-Show Fee : From $5.00" / "Drivers are only allowed to cancel the ride and impose the cancellation fee only if he/she: Is at the pick-up location according to GPS data Has waited more than 5 mins" / "The cancellation fee will only apply from 1 September 2025 • The waiting fee will begin from 14 October 2025"
- 采用：NS-2 同构佐证。无米数。

### C6. ComfortDelGro Taxi — Fares
- URL：https://www.cdgtaxi.com.sg/fares/ （访问 2026-09-28）
- 摘录："Every 400m thereafter or less up to 10km / Every 350m thereafter or less after 10km / Every 45 seconds of waiting or less $0.27" ；豪华车："$20.00 Every additional stop or deviation from pick-up/ drop-off point"
- 采用：RD-3(c)（出租车等待单位）。

### C7. Tada（二手来源，仅作参考不作条款依据）
- URL：https://mothership.sg/2026/03/tada-cancellation-cleaning-fee/ （访问 2026-09-28）
- 摘录："drivers will receive a S$3 compensation if a ride is cancelled after they have been travelling towards the pick-up point for at least three minutes, and are within about 500m of the location"
- 采用：空缺 G2 的参考值（约 500 m 是"在途"判定，不是"到达"判定）。Tada 官方页未找到。

## D. 国际参照与技术文档

### D1. NYC TLC Rules, Chapter 80 — Drivers of Taxicabs, For-Hire Vehicles and Street Hail Liveries
- URL：https://www.nyc.gov/assets/tlc/downloads/pdf/rule_book_current_chapter_80.pdf （访问 2026-09-28）
- 摘录："§80-16(a) Specific Route. (1) The Driver must comply with all reasonable and lawful routing requests of the Passenger. (2) Unless a Passenger makes a specific request, a Driver must proceed to the Passenger's destination by the shortest reasonable route."
- 采用：RD-1、RD-3。

### D2. TfL — London taxi (black cab) driver handbook
- URL：https://content.tfl.gov.uk/taxi-driver-handbook.pdf （访问 2026-09-28）
- 摘录："They will trust you to take them to their destination by the most direct route and not to overcharge them (charge more than is necessary)." / "They may prefer to wait in traffic and go by the most direct route. We take complaints against a taxi driver into consideration"
- 采用：RD-1 背景（乘客可选择"堵也走直路"，与 RD-5 事前同意一致）。

### D3. Uber — Review change in upfront trip price / My final fare was higher than the initial estimate
- URL：https://help.uber.com/en/riders/article/review-change-in-upfront-trip-price?nodeId=f5a6c432-2a21-431e-966d-623087cb24e2 ；https://help.uber.com/en/riders/article/my-final-fare-was-higher-than-the-initial-estimate?nodeId=1e563490-8c32-4cbf-b578-08d84f62a0ba （访问 2026-09-28）
- 摘录："Your upfront price may change if you add stops, update your destination, take additional time at an on-trip stop, or the route or duration of the trip changes significantly." / "You may be charged a different amount than your upfront fare in case the route deviates from the predicted route." / "We are happy to review these cases if you feel you were overcharged."
- 采用：RD-2（绕路多收可复核）；无量化阈值（"significantly"）→ 空缺 G1。

### D4. Uber — Wait time fees and refunds
- URL：https://help.uber.com/en/riders/article/wait-time-fees-and-refunds?nodeId=469f1786-1543-4c83-abbf-ddccb7826fc2 （访问 2026-09-28）
- 摘录："This fee will begin accumulating 2 minutes (5 minutes for Black or Black SUV trips) after your driver arrives."
- 采用：无米数定义 → 空缺 G2 佐证。

### D5. GPS.gov — GPS Accuracy
- URL：https://www.gps.gov/gps-accuracy （访问 2026-09-28）
- 摘录："For example, GPS-enabled smartphones are typically accurate to within a 4.9 m (16 ft.) radius under open sky ( view source at ION.org ). However, their accuracy worsens near buildings, bridges, and trees." / "Many things can degrade GPS positioning accuracy. Common causes include: Satellite signal blockage due to buildings, bridges, trees, etc. Indoor or underground use Signals reflected off buildings or walls ("multipath")"
- 采用：到达半径 200 m（数据层参数；半径远大于手机 GPS 误差量级，判定 612 m 不在上车点不受精度影响）。

## E. 本系统实现（数据层参数与程序规则的出处，不是条款，裁决不得引用）

- 本系统设计，实现于 `core/`（`core/schemas.py` 案件文件格式与 `driver_arrived_at` 200 m 定义；`data/synth/` 合成规则：绕路 / 停留 / 堵车 / 爽约注入，规则 6 的 D<200 m）、§1.5（事实表、F* 引用校验）、§5.3（CaseBrief `void`）、§5.4（Ruling、置信度、escalate）、§5.6（置信度条对阈值）。
- `core/facts/tools.py`：`PICKUP_RADIUS_M=200`、`OFF_ROUTE_M=200`、`DETOUR_MERGE_S=120`、`DETOUR_MIN_KM=0.2`、`STOP_MIN_S=120`、`STOP_RADIUS_M=30`、`THREAT_WORDS`。
- `data/synth/validate.py`：`NEAR_M=300`（路况记录与路线匹配半径）。

## F. 条款来源总表

| 组 | Ryde 一手 | 派生自其他文档 | 系统规则 | 不可引用 / 空缺 |
|---|---|---|---|---|
| RD | RD-5（A7）、RD-6（A10/A11）、RD-3(c) 的 $3 与 RydeTAXI 限制（A9）、RD-2 的"overcharge 属违规"（A10/A11） | RD-1（B1/B2/C2/C4/D1）、RD-2 公式（B5/B4/D3）、RD-3(a)(b)（B1/D1/C4/C2）、RD-3(c) 等待单位（B5/C6/B6）、RD-4（B1 + B7） | 绕路测量、路况匹配参数（数据层） | G1、G3、G4、G5、G6、G10 |
| NS | NS-0、NS-1、NS-2、NS-4、NS-5、NS-6、NS-7（A1–A5、A10、A18、A16）、NS-3（A13/A16/A10） | NS-2 同构佐证（C1/C5）、NS-3（B1 r.25/B2） | 到达半径 200 m（数据层） | NS-5（无字段）、NS-8（Grab/Gojek，无 ETA 字段）、G2、G7 |
| FARE | FARE-1（A8/A6/A9）、FARE-2（A8）、FARE-3（A15/A16） | FARE-1（B6） | — | FARE-3（无数据）、G9 |
| SAFE | SAFE-1（A13）、SAFE-2（A14）、SAFE-3（A10/A12） | — | —（是否构成威胁由法庭阅读判定，不用关键词表） | SAFE-3（无数据） |
