train(123, passenger, 'на платформе 1').
platform(5, free).

conflict(Command1, Command2) :- Command1 \= Command2, share_resource(Command1, Command2).
share_resource(translate(_, P), translate(_, P)).  % Тот же платформа

requires_inspection(Train) :- train(Train, passenger), current_time(T), T > 22.

feasible(translate(Train, Platform)) :- train(Train, _, Status), Status \= 'в пути', platform(Platform, free), not(requires_inspection(Train)).