"""Run: python -m backend.admin --email you@example.com --name Admin. Password prompt only."""
import argparse,getpass
from sqlalchemy import select
from .db import init_db,SessionLocal,User,password_hash,log
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--email',required=True);parser.add_argument('--name',default='Администратор');args=parser.parse_args()
 password=getpass.getpass('Новый пароль (минимум 12 символов): ')
 if len(password)<12 or password!=getpass.getpass('Повторите пароль: '): raise SystemExit('Пароли не совпадают или слишком короткие')
 init_db()
 with SessionLocal() as db:
  email=args.email.lower().strip();u=db.scalar(select(User).where(User.email==email))
  if u: u.role='admin';u.password=password_hash(password);u.blocked='no'
  else: u=User(email=email,name=args.name,password=password_hash(password),role='admin');db.add(u)
  db.flush();log(db,'bootstrap_admin',u.id,{});db.commit()
 print('Администратор создан. Секреты не выведены.')
if __name__=='__main__': main()
