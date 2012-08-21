# -*-coding:utf-8 -*-

import unittest

from dac2 import *

class ModuleTest(unittest.TestCase):

    ###基本运算
    def test_oper1(self):   #测试NEG
        self.assertEquals([],NEG([]))
        a = [1,2,-3,4,-5,6]
        self.assertEquals([-1,-2,3,-4,5,-6],NEG(a))
        a.append(7)
        a.append(-8)
        self.assertEquals([-1,-2,3,-4,5,-6,-7,8],NEG(a))


    def test_oper2(self):   #测试ADD
        self.assertEquals([],ADD([],[]))
        a = [1,2,3,4,5,6]
        b = [10,20,30,40,50,60]
        self.assertEquals([11,22,33,44,55,66],ADD(a,b))
        a.append(7)
        b.append(70)
        self.assertEquals([11,22,33,44,55,66,77],ADD(a,b))

    def test_oper21(self):   #测试ADD
        self.assertEquals([],ADD1([],0))
        a = [1,2,3,4,5,6]
        self.assertEquals([3,4,5,6,7,8],ADD1(a,2))
        a.append(7)
        self.assertEquals([4,5,6,7,8,9,10],ADD1(a,3))

    def test_and(self):   #测试AND
        self.assertEquals([],AND([],[]))
        a = [1,2,3,4,0,6]
        b = [10,-20,30,40,50,60]
        self.assertEquals([True,True,True,True,False,True],AND(a,b))
        a.append(7)
        b.append(70)
        self.assertEquals([True,True,True,True,False,True,True],AND(a,b))
        a.append(9)
        b.append(0)
        self.assertEquals([True,True,True,True,False,True,True,False],AND(a,b))

    def test_gand(self):   #测试AND
        self.assertEquals([],GAND([],[]))
        a = [1,2,3,4,0,6]
        b = [10,-20,30,40,50,60]
        self.assertEquals([True,True,True,True,False,True],GAND(a,b))
        a.append(7)
        b.append(70)
        self.assertEquals([True,True,True,True,False,True,True],GAND(a,b))
        a.append(9)
        b.append(0)
        self.assertEquals([True,True,True,True,False,True,True,False],GAND(a,b))

    def test_gor(self):   #测试AND
        self.assertEquals([],GOR([],[]))
        a = [1,0,3,0,0,6]
        b = [10,-2,30,0,50,60]
        self.assertEquals([True,True,True,False,True,True],GOR(a,b))
        a.append(0)
        b.append(70)
        self.assertEquals([True,True,True,False,True,True,True],GOR(a,b))
        a.append(0)
        b.append(0)
        self.assertEquals([True,True,True,False,True,True,True,False],GOR(a,b))


    def test_DIV(self):   
        self.assertEquals([],DIV([],[]))
        a = [10,20,30,15,50,30]
        b = [1,2,3,4,0,6]
        self.assertEquals([10,10,10,4,50000,5],DIV(a,b))
        a.append(7)
        b.append(70)
        self.assertEquals([10,10,10,4,50000,5,0],DIV(a,b))

    def test_DIV1(self):   
        self.assertEquals([],DIV1([],12))
        a = [10,4,30,15,50,30]
        self.assertEquals([1,0,3,2,5,3],DIV1(a,10))
        a.append(7)
        self.assertEquals([1,0,3,2,5,3,1],DIV1(a,10))


    ##常用指标
    def test_sum(self):
        self.assertEquals([],ACCUMULATE([]))
        a= [1,2,3,4,5,6,7,8,9,0]
        self.assertEquals([1,3,6,10,15,21,28,36,45,45],ACCUMULATE(a))
        a.append(100)
        self.assertEquals([1,3,6,10,15,21,28,36,45,45,145],ACCUMULATE(a))

    def test_msum(self):
        self.assertEquals([],MSUM([],2))
        a= [1,2,3,4,5,6,7,8,9,0]
        self.assertEquals([1,2,3,4,5,6,7,8,9,0],MSUM(a,1))
        self.assertEquals([1,3,5,7,9,11,13,15,17,9],MSUM(a,2))
        a.append(100)
        self.assertEquals([1,3,5,7,9,11,13,15,17,9,100],MSUM(a,2))


    def test_ma(self):
        self.assertEquals([],MA([],3))
        a= [1,2,3,4,5,6,7,8,9,0]
        self.assertEquals([1,2,2,3,4,5,6,7,8,6],MA(a,3))
        a.append(100)
        self.assertEquals([1,2,2,3,4,5,6,7,8,6,36],MA(a,3))

    def test_nma(self):
        self.assertEquals([],NMA([]))
        a= [1,2,3,4,5,6,7,8,9,0]
        self.assertEquals([1,2,2,3,3,4,4,5,5,5],NMA(a))
        a.append(100)
        self.assertEquals([1,2,2,3,3,4,4,5,5,5,13],NMA(a))


    def test_cexpma(self):
        self.assertEquals([],CEXPMA([],6))
        source = [25000,24875,24781,24594,24500,24625,25219,27250]
        self.assertEquals([25000,24958,24899,24797,24698,24674,24856,25654],CEXPMA(source,5))   #相当于5日
        source.append(200000)
        self.assertEquals([25000,24958,24899,24797,24698,24674,24856,25654,83769],CEXPMA(source,5))   #相当于5日


    def test_tr(self):
        self.assertEquals([],TR([],[],[]))
        shigh = [200,250,200,400]
        slow = [100,200,100,200]
        sclose = [150,220,150,300]
        self.assertEquals([100*XBASE,100*XBASE,120*XBASE,250*XBASE],TR(sclose,shigh,slow))
        shigh.append(1000)
        slow.append(500)
        sclose.append(700)
        self.assertEquals([100*XBASE,100*XBASE,120*XBASE,250*XBASE,700*XBASE],TR(sclose,shigh,slow))

    def test_atr(self):
        shigh = [200,250,200,400]
        slow = [100,200,100,200]
        sclose = [150,220,150,300]
        self.assertEquals([100*XBASE,100*XBASE,120*XBASE,250*XBASE],ATR(sclose,shigh,slow,1))
        shigh.append(1000)
        slow.append(500)
        sclose.append(700)
        self.assertEquals([100*XBASE,100*XBASE,120*XBASE,250*XBASE,700*XBASE],ATR(sclose,shigh,slow,1))

    def test_xatr(self):
        self.assertEquals([],XATR([],[],[]))
        shigh = [200,250,200,400]
        slow = [100,200,100,200]
        sclose = [150,220,150,300]
        self.assertEquals([666667,454545,679333,386667],XATR(sclose,shigh,slow))
        shigh.append(1000)
        slow.append(500)
        sclose.append(700)
        self.assertEquals([666667,454545,679333,386667,245171],XATR(sclose,shigh,slow))

    def test_strend(self):
        self.assertEquals([],STREND([]))
        self.assertEquals([0],STREND([1]))        
        source = [10,20,30,30,40,50,40,30,20,20,10,20]
        self.assertEquals([0,1,2,3,4,5,-1,-2,-3,-4,-5,1],STREND(source))
        source.append(20)
        self.assertEquals([0,1,2,3,4,5,-1,-2,-3,-4,-5,1,2],STREND(source))
        source.append(30)
        self.assertEquals([0,1,2,3,4,5,-1,-2,-3,-4,-5,1,2,3],STREND(source))
        source.append(20)
        self.assertEquals([0,1,2,3,4,5,-1,-2,-3,-4,-5,1,2,3,-1],STREND(source))
        source.append(10)
        self.assertEquals([0,1,2,3,4,5,-1,-2,-3,-4,-5,1,2,3,-1,-2],STREND(source))


    def test_tmax(self):
        self.assertEquals([],TMAX([],10))
        source = [10,12,3,2,5,100,0,13,16,9]
        self.assertEquals([10,12,3,2,5,100,0,13,16,9],TMAX(source,1))
        self.assertEquals([10,12,12,3,5,100,100,13,16,16],TMAX(source,2))
        source.append(3)
        source.append(30)
        self.assertEquals([10,12,12,3,5,100,100,13,16,16,9,30],TMAX(source,2))
        self.assertEquals([10,12,12,12,5,100,100,100,16,16,16,30],TMAX(source,3))

    def test_tmin(self):
        self.assertEquals([],TMIN([],10))
        source = [10,12,3,2,5,100,0,13,16,9]
        self.assertEquals([10,12,3,2,5,100,0,13,16,9],TMIN(source,1))
        self.assertEquals([10,10,3,2,2,5,0,0,13,9],TMIN(source,2))
        source.append(3)
        source.append(30)
        self.assertEquals([10,10,3,2,2,5,0,0,13,9,3,3],TMIN(source,2))
        self.assertEquals([10,10,3,2,2,2,0,0,0,9,3,3],TMIN(source,3))

    def test_cross(self):   #
        self.assertEquals([],UPCROSS([],[]))
        target = [10,20,30,40,50,40,30,20,10,12,11,12]
        follow = [5,15,35,41,60,50,25,26,8,12,13,12]
        self.assertEquals([0,0,1,0,0,0,0,1,0,0,1,0],UPCROSS(target,follow))
        self.assertEquals([1,0,0,0,0,0,1,0,1,0,0,0],DOWNCROSS(target,follow))
        target.append(15)
        follow.append(11)
        self.assertEquals([0,0,1,0,0,0,0,1,0,0,1,0,0],UPCROSS(target,follow))
        self.assertEquals([1,0,0,0,0,0,1,0,1,0,0,0,1],DOWNCROSS(target,follow))
        target.append(13)
        follow.append(25)
        self.assertEquals([0,0,1,0,0,0,0,1,0,0,1,0,0,1],UPCROSS(target,follow))
        self.assertEquals([1,0,0,0,0,0,1,0,1,0,0,0,1,0],DOWNCROSS(target,follow))

    def test_ref(self):
        self.assertEquals([],REF([]))
        a= [1,2,3,4,5,6,7,8,9,0]
        self.assertEquals([1,2,3,4,5,6,7,8,9,0],REF(a,0))
        self.assertEquals([1,1,2,3,4,5,6,7,8,9],REF(a,1))
        self.assertEquals([1,1,1,2,3,4,5,6,7,8],REF(a,2))
        self.assertEquals([1,1,1,1,1,1,1,1,1,2],REF(a,8))
        self.assertEquals([1,1,1,1,1,1,1,1,1,1],REF(a,9))
        self.assertEquals([1,1,1,1,1,1,1,1,1,1],REF(a,10))
        self.assertEquals([1,1,1,1,1,1,1,1,1,1],REF(a,11))
        self.assertEquals([1,1,1,1,1,1,1,1,1,1],REF(a,100))
        a.append(100)
        self.assertEquals([1,1,1,2,3,4,5,6,7,8,9],REF(a,2))



if __name__ == "__main__":
    import logging
    logging.basicConfig(filename="test.log",level=logging.DEBUG,format='%(name)s:%(funcName)s:%(lineno)d:%(asctime)s %(levelname)s %(message)s')
    
    unittest.main()
