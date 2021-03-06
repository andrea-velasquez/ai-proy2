import io
import pandas as pd
import numpy as np
import itertools
import copy
import math
import csv

#@title Bayes Network Class
class BayesNetwork():
  def __init__(self, df, matrix=None, matrix_dict=None, factors=None):
    self.df = df
    self.M = len(df.index)
    self.vars = {name: Var(name, df) for name in df} # Diccionario con { name: Var(name) }
    self.structure = Structure(self)
    if factors is not None:
      self.matrix_dict = self.factors2matrix_dict(factors)
      self.factors = factors
    elif matrix is not None or matrix_dict is not None:
      self.matrix_dict = matrix_dict if matrix_dict else self.matrix2dict(matrix)
      self.factors = self.matrix_dict2factors(self.matrix_dict) # dict of P objects

  def matrix2dict(self, matrix):
    m_dict = {}
    for r in range(len(matrix)):
      X =  self.df.columns[r]
      m_dict[X] = set()
      for c in range(len(matrix)):
        if matrix[r][c]:
          m_dict[X].add(self.df.columns[c])
    return m_dict
  
  def matrix_dict2factors(self, matrix_dict):
    factors = {}
    for X, Y in matrix_dict.items():
      factors[X] = P(self.df, X, list(Y))
    return factors
  
  def factors2matrix_dict(self,factors):
    m = {}
    for f in factors.values(): m[f.X] = set(f.Y)
    return m

  def topologicalSortUtil(self, i,var, visited, stack): 
    visited[i] = True
    for j,parent in enumerate(self.matrix_dict[var]): 
      if visited[j] == False: 
        self.topologicalSortUtil(j,parent, visited, stack)
    stack.append(var) 


  def topologicalSort(self,vars):
    visited = [False]*len(vars)
    stack = [] 
    for i,var in enumerate(vars): 
      if visited[i] == False: 
        self.topologicalSortUtil(i,var, visited, stack)
    return stack

  def predict(self, target, variables=[], values=[], alpha=1):
    factors = {",".join(f.vars): copy.deepcopy(f) for f in self.factors.values()}

    hidden_vars = [v for v in self.df if v not in variables and v!=target]
    hidden_vars = self.topologicalSort(hidden_vars)

    # Reduce factor tables if some values are known
    for factor in factors.values():
      selected = {var:val for var, val in zip(variables, values) if var in factor.vars}
      if selected:
        factor.filterDistribution(selected.keys(), selected.values(), alpha, replace=True)

    for v in hidden_vars:
      factors = self.eliminate_var(v, factors)

    iterfactors = iter(factors.values())
    prediction = next(iterfactors)
    for factor in iterfactors:
      prediction = prediction.product(factor)

    return prediction.distribution() #[[target, "P"]].groupby(target).sum().reset_index()

  def eliminate_var(self, to_eliminate, factors):
    factors_with_eliminate = {}
    factors_without_eliminate = {}
    for f in factors.values():
      if to_eliminate in f.vars:
        factors_with_eliminate[",".join(f.vars)] = f
      else:
        factors_without_eliminate[",".join(f.vars)] = f

    iterfactors = iter(factors_with_eliminate.values())
    new_factor = next(iterfactors)
    for factor in iterfactors:
      new_factor = new_factor.product(factor)
    
    if new_factor.distribution().columns.drop(["P", to_eliminate]).empty:
      return factors_without_eliminate
    new_factor = new_factor.marginalization(to_eliminate) ###

    new_factor_key = ",".join(new_factor.vars)
    if new_factor_key in factors_without_eliminate:
      new_factor = new_factor.product(factors_without_eliminate[new_factor_key])
    
    # factors_without_eliminate U new_factor
    factors_without_eliminate[new_factor_key] = new_factor
    return factors_without_eliminate

  def structureScore(self, metric, params={}):
    assert metric in ["entropy", "AIC", "MDL"], "Invalid metric. Accepted metrics: 'entropy', 'AIC', 'MDL'."
    return getattr(self.structure, metric+"_metric")(**params)

  def bestStructure(self, metric, algorithm, metric_params={}, algorithm_params={}):
    assert metric in ["entropy", "AIC", "MDL", "K2"], "Invalid metric. Accepted metrics: 'entropy', 'AIC', 'MDL', 'K2'."
    assert algorithm in ["K2", "greedy"], "Invalid algorithm. Accepted algorithms: 'K2', 'greedy'."
    assert not (metric=="K2" and algorithm=="greedy"), "K2 metric can only be used with K2 algorithm"

    metric_func = getattr(self.structure, metric+"_metric")
    return getattr(self.structure, algorithm+"_algorithm")(metric=metric_func, metric_params=metric_params, **algorithm_params)


#@title Structure Class
class Structure():
  def __init__(self, bayes):
    self.b = bayes
  
# Metrics
  def entropy_metric(self, factors=None, alpha=1):
    if factors is None:
      factors = self.b.factors

    logE = 0
    # iterar sobre variables
    for f in factors.values():
      # obtener las variables del factor de la variable
      f_vars = f.vars.keys()
      f_vals_combinations = itertools.product(*[v.values() for v in f.vars.values()])
      # iterar sobre valores que pueden tomar las variables del factor
      for f_vals in f_vals_combinations:
        prob = f.probability(f_vars, f_vals, scalar=True)
        join_prob = f.join_probability(f_vals)
        # m = Var.M(self.b.df, f_vars, f_vals)
        logE += join_prob*np.log2(prob)
    return logE*len(self.b.df.index)*-1

  def AIC_metric(self, factors=None, alpha=1):
    if factors is None: factors = self.b.factors

    return self.entropy_metric(factors, alpha) + self.__k(factors)

  def MDL_metric(self, factors=None, alpha=1):
    if factors is None: factors = self.b.factors

    return self.entropy_metric(factors, alpha) + self.__k(factors)/2*np.log2(self.b.M)

  def __k(self, factors):
    k = 0
    for f in factors.values():
      qi = 1
      for y in f.Y:
        qi *= f.vars[y].card()
      # K=∑(ri−1)×qi -- ri = f.vars[f.X].card()
      k += (f.vars[f.X].card()-1)*qi
    return k

  def K2_metric(self,p):
    var=p.X
    parents=p.Y
    total = 1
    if(len(parents)>0):
      parents_comb  = itertools.product(*[self.b.vars[p].values() for p in parents])
      for p in parents_comb:
        Nij=0
        parents_comb_val = [self.b.vars[parents[i]].values()[int(p[i])] for i in range(len(p))]
        for val in self.b.vars[var].values() :
          count = Var.M(self.b.df,[var,*parents],[val,*parents_comb_val])
          total*=math.factorial(count)
          Nij+=count
        total*=math.factorial(self.b.vars[var].card()-1)/math.factorial(Nij+self.b.vars[var].card()-1)
    else:
      Nij=0
      for val in self.b.vars[var].values():
        count = Var.M(self.b.df,[var],[val])
        total*=math.factorial(count)
        Nij+=count
      total*=math.factorial(self.b.vars[var].card()-1)/math.factorial(Nij+self.b.vars[var].card()-1)

    return total

# Search algoritms
  def K2_algorithm(self, metric, max_parents, nodes_order=None, metric_params={}):
    total_spaces = [1,1,3,25,543,29281,3781503,1138779265,
 783702329343,1213442454842881,4175098976430598143,
 31603459396418917607425,
 521939651343829405020504063,
 18676600744432035186664816926721,
 1439428141044398334941790719839535103]
    if nodes_order is None:
      nodes = list(self.b.vars.keys())
    else:
      nodes = nodes_order
    struct={}
    steps=0
    for i in range(len(nodes)):
      struct[nodes[i]]=P(self.b.df,nodes[i],[])
      Po = metric(struct[nodes[i]]) if self.K2_metric == metric else metric(factors=struct, **metric_params) 
      proceed = True
      previ=[x for x in range(i)]
      while(proceed and len(struct[nodes[i]].Y)<max_parents):
        
        maxP=0
        maxi=0
        for zi in previ:
          steps+=1
          temp_struct = copy.deepcopy(struct)
          temp_struct[nodes[i]]=P(self.b.df,nodes[i],temp_struct[nodes[i]].Y+[nodes[zi]])
          Pn=metric(temp_struct[nodes[i]]) if self.K2_metric == metric else metric(factors=temp_struct, **metric_params)
          if(Pn>maxP):
            maxP=Pn
            maxi=zi
        if(maxP>Po):
          Po=maxP
          struct[nodes[i]]=P(self.b.df,nodes[i],struct[nodes[i]].Y+[nodes[maxi]])
          previ.remove(maxi)
        else:
          proceed = False
    p_visited=(100*steps)/total_spaces[len(nodes)]
    return struct, Po , p_visited

  def greedy_algorithm(self, metric, start_unconnected=True, verbosed=True, visit_space=None, metric_params={}):
    vars = list(self.b.vars.keys())
    operators = [self.remove_edge, self.add_edge,self.reverse_edge, self.reverse_edge]

    if start_unconnected: best = {v:set() for v in vars}
    else: best = self.b.matrix_dict

    max_seen_cases = -1
    if visit_space is not None:
      total_space = math.pow(2, (len(vars)*(len(vars)-1)))
      max_seen_cases = total_space*visit_space

    best_score = metric(factors=self.b.matrix_dict2factors(best), **metric_params)

    seen_cases = 0
    candidate = best
    for v1_i in range(len(vars)):
      v1 = vars[v1_i]
      for v2_i in range(v1_i+1, len(vars)):
        v2 = vars[v2_i]
        cand_score = -9999
        to_reverse = []
        for op_i, op in enumerate(operators):
          seen_cases+=1
          if verbosed and seen_cases%10==0:
            print(f"{seen_cases} cases seen. Best score: {best_score}\nStructure: {best}\n")
          if op(candidate, v1, v2):
            cand_score = max(cand_score, metric(factors=self.b.matrix_dict2factors(candidate), **metric_params))
        if cand_score>best_score:
          best_score = cand_score
        else:
          # Not progress
          if max_seen_cases==-1 or seen_cases>=max_seen_cases:
            return best, best_score, seen_cases
            
    return best, best_score, seen_cases

  def creates_cycle(self, graph, target, start):
    # hay algún camino de start a target?
    if target == start: return True
    for destination in graph[start]:
      if self.creates_cycle(graph, target, destination) : return True
    return False

  def add_edge(self, graph, v1, v2):
    # graph is { "var_name": set(var_names) }
    if self.creates_cycle(graph, v1, v2): return False
    added = v2 not in graph[v1]
    graph[v1].add(v2)
    return added

  def remove_edge(self, graph, v1, v2):
    # graph is { "var_name": set(var_names) }
    removed = v2 in graph[v1]
    graph[v1].discard(v2)
    return removed

  def reverse_edge(self, graph, v1, v2):
    # graph is { "var_name": set(var_names) }
    if v2 in graph[v1]: # edge exists
      graph[v1].discard(v2)
      if self.add_edge(graph, v2, v1):
        return True
      graph[v1].add(v2)
      return False
    

#@title Probability Class
class P():
  def __init__(self, df=None, X=None, Y=[]):
    self.X = X
    self.Y = Y
    self.df = df
    if df is not None:
      self.M = df.shape[0]
    if X:
      self.vars = {name: Var(name, df) for name in [X]+Y} # Diccionario con { name: Var(name) }
    self.dist_table = [None, None] # table and alpha
    self.joindist_table = [None, None] # table and alpha

  def __str__(self):
     return f"P({self.X}|{','.join(self.Y)})" if self.Y else f"P({self.X})"
  
  def __repr__(self):
     return str(self)

  def filterDistribution(self, variables, values, alpha=1, replace=False, forceRecalc=False):
    dist = self.distribution(alpha, forceRecalc)
    query = " & ".join(f"{var}=='{val}'" for var, val in zip(variables, values))

    filtered = dist.query(query)
    if replace:
      self.dist_table[0] = filtered
      self.dist_table[1] = alpha
    return filtered

  def distribution(self, alpha=1, forceRecalc=False):
    # Avoid recalculating unless forceRecalc=True
    if forceRecalc or self.dist_table[0] is None or self.dist_table[1]!=alpha:
      self.dist_table[0] = self.dist_margin(alpha) if not self.Y else self.dist_cond(alpha)
      self.dist_table[1] = alpha
    return self.dist_table[0]

  def join_distribution(self, alpha=1, forceRecalc=False):
    if forceRecalc or self.joindist_table[0] is None or self.joindist_table[1]!=alpha:
      ps = []
      vars_names = list(self.vars.keys())
      vals_combinations = itertools.product(*[v.values() for v in self.vars.values()])
      for vals in vals_combinations:
        vals = list(vals)
        # ((M[X,Y]+α) / (M+α*Πcards(X,Y)))  / ((M[Y]+α) / (M+α*Πcards(Y)))
        prod_cards=1
        for var in self.vars.values(): prod_cards*=var.card()
        p = (Var.M(self.df, vars_names, vals) + alpha) / (self.M + alpha*prod_cards)

        vals.append(p)
        ps.append(vals) # x1, y1.. yn, P

      # Crear factor (como dataframe) de los resultados
      dist = pd.DataFrame(ps, columns=vars_names+["P"])

      self.joindist_table[0] = dist
      self.joindist_table[1] = alpha

    return self.joindist_table[0]

  def probability(self, variables, values, alpha=1, scalar=False, forceRecalc=False):
    # If scalar = False: Returns a dataframe with one row
    # If scalar = True: Returns the probability as a float

    assert len(variables) == len(values), "Must provide same number of variables and values"

    filteredDist = self.filterDistribution(variables, values, alpha, forceRecalc)
    return filteredDist["P"].item() if scalar else filteredDist

  def join_probability(self, values, variables=[], alpha=1):
    if not variables: variables = list(self.vars.keys())
    assert len(variables) == len(self.vars), "Must provide list with same number of variables as P.vars"
    assert len(values) == len(self.vars), "Must provide values for all variables in P.vars"

    dist = self.join_distribution(alpha)
    query = " & ".join(f"{var}=='{val}'" for var, val in zip(variables, values))

    return dist.query(query)["P"].item()

  
  def dist_margin(self, alpha):
    # (M[var=val]+α) / (M+α*card(var))
    variable = self.vars[self.X]
    values = variable.values()

    dist = []
    for val in values:
      dist.append((variable.ocurrences(val)+alpha) / (self.M+alpha*variable.card()))

    return pd.DataFrame({self.X: values, "P": dist})

  def dist_cond(self, alpha):
    X = self.vars[self.X]
    vars = [self.X]+self.Y
    ps = []
    for x_val in X.values():
      y_vals_combinations = itertools.product(*[self.vars[y].values() for y in self.Y])
      for y_vals in y_vals_combinations:
        vals = [x_val, *y_vals]
        
        # ((M[X,Y]+α) / (M+α*Πcards(X,Y)))  / ((M[Y]+α) / (M+α*Πcards(Y)))
        prod_cards = np.prod([var.card() for var in self.vars.values()])
        p = (Var.M(self.df, vars, vals) + alpha) / (self.M + alpha*prod_cards)
        p /= (Var.M(self.df, self.Y, y_vals) + alpha) / (self.M + alpha*prod_cards/X.card())

        vals.append(p)
        ps.append(vals) # x1, y1.. yn, P

    # Crear factor (como dataframe) de los resultados
    vars.append("P")
    dist = pd.DataFrame(ps, columns=vars)

    # Normalizar
    dist["P"] = dist.groupby(self.Y).transform(lambda x: x/(x.sum()))

    return dist

  def product(self, P2):
    return T(P.product_dfs(self.distribution(), P2.distribution()), self.dist_table[1])

  def marginalization(self, on):
    return T(P.marginalization_dfs(self.distribution(), on), self.dist_table[1])

  def product_dfs(dfP1, dfP2):
    # tienen columna en común
    if not (dfP1.columns & dfP2.columns).drop("P").empty:
      dfP1 = dfP1.set_index(list(dfP1.columns.drop("P")))
      dfP2 = dfP2.set_index(list(dfP2.columns.drop("P")))

      return dfP1.mul(dfP2,axis=0).reset_index()

    # no tienen nada en común
    if len(dfP1.index)==1: # número de filas es 1
      scalar = dfP1["P"].item()
      df = dfP2
    else:
      display()
      scalar = dfP2["P"].item()
      df = dfP1
    df["P"] *= float(scalar)
    return df

  def marginalization_dfs(dfP, on):
    groupOn = list(dfP.columns.drop(["P", on]))
    return dfP.groupby(groupOn).sum().reset_index()




#@title T class
class T(P):
  def __init__(self, table, alpha):
    self.dist_table = [table, alpha]
    self.vars = list(table.columns.drop("P"))

  def __str__(self):
    return f"T({','.join(self.vars)})"
  
  def distribution(self):
    return self.dist_table[0]



#@title Variable class
class Var():
  def __init__(self, name, df):
    self.name = name
    self.df = df

  def __str__(self):
    return self.name

  def __repr__(self):
     return str(self)
  
  def values(self):
    # valores que puede tomar la variable
    return list(self.df[self.name].unique())
  
  def card(self):
    # cardinalidad de la variable
    return len(self.df[self.name].unique())

  def ocurrences(self, value):
    # M[name=value]
    return Var.M(df, [self.name], [value])

  # static method
  def M(df, variables, values):
    # M[variables=values]
    assert len(variables) == len(values), "Must provide same number of variables and values"
    query = " & ".join(f"{var}=='{val}'" for var, val in zip(variables, values))
    return df.query(query).shape[0]



def call_k2(m, max_p, nodes_order):
  return bayes.bestStructure(
      metric=m,
      algorithm="K2",
      algorithm_params={"max_parents": max_p, "nodes_order": nodes_order}
    )

spaces = [1,1,3,25,543,29281,3781503,1138779265,
 783702329343,1213442454842881,4175098976430598143,
 31603459396418917607425,
 521939651343829405020504063,
 18676600744432035186664816926721,
 1439428141044398334941790719839535103]


visit_space = .25
vars_order = ["A", "B", "C", "D", "E", "F", "G"]
metric = "K2"
verb_checkbox = True
matrix = [[0]*7 for i in range(7)]

#@title Inicializar Red Bayesiana
bayes = BayesNetwork(pd.read_csv("dataset.csv", dtype=str), matrix=matrix)

with open("output.txt", "w") as file:
  to_visit = spaces[len(bayes.vars)]*visit_space
  visited_space = 0
  m=len(bayes.vars)-1
  c = 0
  best_score = -999
  for permutation in list(itertools.permutations(vars_order)):
    c+=1
    file.write(f"[{c}]Trying permutation: {permutation}\n")
    print(f"[{c}] Trying permutation:", permutation)
    factors, score, vis = call_k2(metric, m, permutation)
    visited_space+=vis
    if score>best_score:
      best_score = score
      best_factor = factors
      
    if verb_checkbox: 
      file.write(f"Porcentaje de espacio visitado: {visited_space}\n")
      file.write(f"Mejor estructura: {best_factor} con puntaje {best_score}\n\n")
      print(f"Porcentaje de espacio visitado: {visited_space}")
      print(f"Mejor estructura: {best_factor} con puntaje {best_score}")
    if visited_space>=to_visit:
      break
 
  file.write("ESTRUCTURA ENCONTRADA\n")
  file.write(f"Puntaje: {best_score}\n")
  file.write(f"Estructura: {best_factor}\n")
  file.write(f"Vistos: {visited_space}")

  print("ESTRUCTURA ENCONTRADA")
  print("Puntaje:", best_score)
  print("Estructura:", best_factor)
  print("Vistos:", visited_space)
