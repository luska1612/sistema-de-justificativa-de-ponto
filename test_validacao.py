from app import nome_valido, matricula_valida

assert nome_valido('João Silva')
assert not nome_valido('João123')
assert matricula_valida('12345')
assert not matricula_valida('A001')
print('Validações OK')
