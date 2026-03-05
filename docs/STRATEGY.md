Here is a "set it and forget it" flow chart that uses only two reliable inputs you already have every 3 minutes: ComEd price and local inverter solar power. Weather is optional and not required.

The design goal: fill the battery when solar is available, then spend it during expensive grid hours, while avoiding dumb cycling and avoiding running out too early in the evening.

FLOW CHART

A. Always run these guards first
	1.	If battery SoC <= Hard Reserve (example 20% winter, 10% summer)
Then: do not discharge (grid supplies load). Stop.
	2.	If inverter solar power is unavailable (night or inverter off)
Then: go to Night logic (section D).
	3.	Otherwise solar is available
Then: go to Daylight logic (section B).

B. Daylight logic (solar capture mode)
Goal: charge from solar. Avoid discharging unless prices are extreme or you need headroom to avoid wasting solar.
	1.	Compute "Solar Surplus"
Solar Surplus = solar generation minus house load.
If you cannot measure load, approximate surplus by battery charging rate or net export if available.
If Surplus > 0, solar can charge the battery. If Surplus <= 0, solar is not covering load.
	2.	If Surplus > 0 (solar is excess)
2a. If SoC < Afternoon Target SoC (example 90% summer, 70% winter)
Then: force no discharge. Let solar charge. Stop.
2b. If SoC >= Afternoon Target SoC
Then: create headroom only if needed.
	*	If battery is near full and you are exporting or clipping solar, allow limited discharge to keep SoC in a "headroom band" (example 85 to 95%), but only when price is not cheap.
	*	If not exporting, do not discharge. Stop.
	3.	If Surplus <= 0 (solar not excess, likely clouds or high load)
3a. If current price is in an "Extreme" band (example >= 20 cents)
Then: allow discharge down to Extreme Floor (example 10% summer, 20% winter). Stop.
3b. Else: do not discharge. Preserve SoC for evening. Stop.

C. Transition trigger (when to switch to evening behavior)
If local time >= Peak Start (example 4:00pm) OR inverter solar power has been below a small threshold for 20 to 30 minutes (sun is going away)
Then: switch to Peak logic (section E).

D. Night logic (no solar refill)
Goal: preserve battery unless prices are painful.
	1.	If time is inside Peak Window (example 4pm to 10pm)
Then: go to Peak logic (section E).
	2.	Else (late night, early morning)
	*	Discharge only if price >= Extreme band.
	*	Otherwise hold SoC above a conservative Night Floor (example 30 to 40% winter, 20 to 30% summer).

E. Peak logic (evening arbitrage mode)
Goal: spend battery when prices are high, but pace it so you do not dump it all at 5pm.
	1.	Determine Season Mode
Summer mode: May to September or when daily solar is consistently strong.
Winter mode: October to April or when daily solar is inconsistent.
	2.	Select SoC Floor from price bands (your idea, season adjusted)
Example summer floors (peak window):

	*	price < 8c: floor 50%
	*	8c to 10c: floor 30%
	*	10c to 20c: floor 20%
	*	= 20c: floor 10%

Example winter floors (peak window, more conservative):
	*	price < 8c: floor 60%
	*	8c to 10c: floor 45%
	*	10c to 20c: floor 30%
	*	= 20c: floor 20% (optionally 15% if you accept more risk)

	3.	Add pacing (prevents early depletion)
Compute "Usable Energy" = battery energy above the selected floor.
Compute "Remaining Peak Hours" = hours until Peak End (example 10pm).
Define a soft rule: do not spend more than Usable Energy / Remaining Peak Hours in the next hour unless price is in the top band.

Operationally this means:
	*	If price is moderate: discharge gently, saving energy.
	*	If price is very high: discharge hard, down to the floor.

	4.	Execute discharge decision
If SoC > Floor AND (price is above your discharge threshold)
Then: discharge to cover load, but do not go below Floor and respect pacing unless in top band.
Else: do not discharge.

F. Simple reliability tricks for your 3 minute scheduler
	1.	Hysteresis: require price to stay above a band boundary for 2 consecutive checks before switching bands. Same for dropping bands. This prevents flapping.
	2.	Minimum hold time: once you enter "Peak logic," stay there until Peak End even if price dips briefly.
	3.	Token friction: do not send EPcube control commands unless the desired state has been stable for 2 to 3 cycles.

That is the complete conceptual flow. It relies on solar power being measurable locally, ComEd price being available, and no weather data. It also matches your band concept and adds the two things that usually matter most in practice: seasonal conservatism and evening pacing.
